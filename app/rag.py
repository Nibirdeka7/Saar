import math
import re
from collections import Counter
from typing import Dict, List, Tuple

import boto3
from app.aws import answer as bedrock_chat, embed, client as aws_client
from app.config import settings
from app.db import connection
from app.vector import search as pinecone_search

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does",
    "for", "from", "has", "have", "how", "i", "in", "is", "it", "its", "of",
    "on", "or", "that", "the", "their", "this", "to", "was", "what", "when",
    "where", "which", "who", "why", "will", "with", "you", "your",
}


def tokenize(text: str) -> List[str]:
    return [
        w for w in re.findall(r"[a-z0-9_-]+", text.lower())
        if len(w) > 1 and w not in STOP_WORDS
    ]


# 1. Contextual Query Rewriting + Multi-Query Expansion
def rewrite_queries(question: str, history: List[Dict]) -> List[str]:
    cfg = settings()
    recent = history[-(cfg.memory_turns * 2):]
    hist_str = "\n".join(
        f"{m['role'].capitalize()}: {m['content'][:250]}" for m in recent
    )

    prompt = (
        "Rewrite the user's question into 2 standalone search queries for an enterprise document search engine. "
        "Resolve any pronouns ('it', 'that', 'they', 'this') using the conversation history. "
        "Include exact policy IDs, numbers, or domain synonyms if relevant. "
        "Return ONLY the rewritten queries, one per line, without numbering or bullets.\n\n"
        f"Conversation history:\n{hist_str or '(none)'}\n\nUser question: {question}"
    )
    variants = [question]
    try:
        raw = bedrock_chat(prompt, "", [])
        for line in raw.splitlines():
            cleaned = line.strip(" -*0123456789.").strip()
            if cleaned and cleaned.lower() != question.lower():
                variants.append(cleaned)
    except Exception:
        pass
    return variants[:3]


# 2. Tenant-Scoped Okapi BM25 Keyword Search over PostgreSQL Parent Chunks
def bm25_search_db(tenant_id: str, query: str, top_k: int) -> List[Dict]:
    q_tokens = tokenize(query)
    if not q_tokens:
        return []

    with connection() as conn:
        rows = conn.execute(
            "SELECT parent_id, document_id, title, page_number, section, content "
            "FROM parent_chunks WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchall()

    if not rows:
        return []

    parsed_rows = []
    for r in rows:
        if isinstance(r, dict):
            parsed_rows.append((
                r["parent_id"], r["document_id"], r["title"],
                r["page_number"], r["section"], r["content"]
            ))
        else:
            parsed_rows.append(tuple(r))

    docs_tokens = [tokenize(r[5]) for r in parsed_rows]
    avg_dl = sum(len(t) for t in docs_tokens) / max(len(docs_tokens), 1)
    n_docs = len(parsed_rows)

    df = Counter()
    for tokens in docs_tokens:
        for t in set(tokens):
            df[t] += 1

    k1, b = 1.5, 0.75
    scored = []
    for row, d_tokens in zip(parsed_rows, docs_tokens):
        tf = Counter(d_tokens)
        dl = len(d_tokens)
        score = 0.0
        for qt in q_tokens:
            if qt not in tf:
                continue
            idf = math.log((n_docs - df[qt] + 0.5) / (df[qt] + 0.5) + 1.0)
            num = tf[qt] * (k1 + 1.0)
            den = tf[qt] + k1 * (1.0 - b + b * (dl / max(avg_dl, 1.0)))
            score += idf * (num / den)
        if score > 0:
            scored.append((score, row))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "id": r[0],
            "score": score,
            "metadata": {
                "parent_id": r[0],
                "document_id": r[1],
                "title": r[2],
                "page": r[3],
                "section": r[4],
                "text": r[5],
            },
        }
        for score, r in scored[:top_k]
    ]


# 3. Hybrid Dense + Sparse Reciprocal Rank Fusion (RRF) + Parent Context Recovery
def hybrid_retrieve_and_recover(principal, queries: List[str]) -> List[Dict]:
    cfg = settings()
    rrf_k = 60
    rrf_scores: Dict[str, float] = {}
    hit_map: Dict[str, Dict] = {}

    for q in queries:
        vec_hits = pinecone_search(
            principal.tenant, embed(q), principal.groups, principal.subject, limit=cfg.vector_top_k
        )
        for rank, h in enumerate(vec_hits[:cfg.vector_top_k]):
            pid = h["metadata"].get("parent_id") or h["id"]
            rrf_scores[pid] = rrf_scores.get(pid, 0.0) + 1.0 / (rrf_k + rank)
            hit_map[pid] = h

        kw_hits = bm25_search_db(principal.tenant, q, cfg.bm25_top_k)
        for rank, h in enumerate(kw_hits):
            pid = h["metadata"]["parent_id"]
            rrf_scores[pid] = rrf_scores.get(pid, 0.0) + 1.0 / (rrf_k + rank)
            if pid not in hit_map:
                hit_map[pid] = h

    top_pids = sorted(
        rrf_scores, key=lambda pid: rrf_scores[pid], reverse=True
    )[:cfg.hybrid_top_k]
    if not top_pids:
        return []

    # Swap small child chunks for full parent chunks from PostgreSQL
    parent_texts: Dict[str, str] = {}
    with connection() as conn:
        rows = conn.execute(
            "SELECT parent_id, content FROM parent_chunks "
            "WHERE tenant_id = %s AND parent_id = ANY(%s)",
            (principal.tenant, top_pids),
        ).fetchall()
        for r in rows:
            pid = r["parent_id"] if isinstance(r, dict) else r[0]
            content = r["content"] if isinstance(r, dict) else r[1]
            parent_texts[pid] = content

    recovered = []
    for pid in top_pids:
        item = dict(hit_map[pid])
        meta = dict(item["metadata"])
        if pid in parent_texts:
            meta["text"] = parent_texts[pid]
        item["metadata"] = meta
        item["rrf_score"] = rrf_scores[pid]
        recovered.append(item)
    return recovered


# 4. Cross-Encoder Reranking (Amazon Bedrock Rerank + Lexical Fallback)
def rerank_passages(question: str, passages: List[Dict]) -> List[Dict]:
    if not passages:
        return []
    cfg = settings()

    try:
        try:
            client = aws_client("bedrock-agent-runtime")
        except Exception:
            client = boto3.client("bedrock-agent-runtime", region_name=cfg.aws_region)
        resp = client.rerank(
            queries=[{"type": "TEXT", "textQuery": {"text": question}}],
            sources=[
                {
                    "type": "INLINE",
                    "inlineDocumentSource": {
                        "type": "TEXT",
                        "textDocument": {"text": p["metadata"].get("text", "")[:4000]},
                    },
                }
                for p in passages
            ],
            rerankingConfiguration={
                "type": "BEDROCK_RERANKING_MODEL",
                "bedrockRerankingConfiguration": {
                    "numberOfResults": min(cfg.rerank_top_n, len(passages)),
                    "rerankingModelConfiguration": {
                        "modelArn": f"arn:aws:bedrock:{cfg.aws_region}::foundation-model/{cfg.bedrock_rerank_model}"
                    },
                },
            },
        )
        ranked = []
        for r in resp.get("results", []):
            p = dict(passages[r["index"]])
            p["score"] = float(r["relevanceScore"])
            ranked.append(p)
        return ranked
    except Exception:
        # Pure-Python normalized query-term coverage + RRF tie-breaker
        q_tokens = set(tokenize(question))
        for p in passages:
            d_tokens = set(tokenize(p["metadata"].get("text", "")))
            overlap = len(q_tokens & d_tokens) / max(len(q_tokens), 1)
            rrf_bonus = min(p.get("rrf_score", 0.0) * 5.0, 0.25)
            p["score"] = round(min(overlap + rrf_bonus, 1.0), 4)
        passages.sort(key=lambda x: x["score"], reverse=True)
        return passages[:cfg.rerank_top_n]


# 5. Threshold Filtering & Context Character Budgeting
def refine_passages(passages: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    cfg = settings()
    relevant = [p for p in passages if p.get("score", 0.0) >= cfg.min_relevance]

    selected = []
    used_chars = 0
    for p in relevant:
        text = p["metadata"].get("text", "")
        if used_chars + len(text) > cfg.max_context_chars and selected:
            break
        selected.append(p)
        used_chars += len(text)

    sources = [
        {
            "index": i + 1,
            "document_id": p["metadata"].get("document_id", ""),
            "title": p["metadata"].get("title", "Document"),
            "page": p["metadata"].get("page", 1),
            "section": p["metadata"].get("section", ""),
            "score": round(p.get("score", 0.0), 3),
            "excerpt": p["metadata"].get("text", "")[:320],
        }
        for i, p in enumerate(selected)
    ]
    return selected, sources


def chat(p, question: str, history=None):
    from app.graph import chat as _chat
    return _chat(p, question, history=history)

