import argparse
import json
import re
import statistics
import time
from pathlib import Path

import boto3
from app.auth import Principal
from app.config import settings
from app.graph import chat


def get_benchmark_principal() -> Principal:
    return Principal(
        subject="benchmark@novacore.internal",
        tenant="demo-workspace",
        groups=("workspace",),
        admin=True,
        email="benchmark@novacore.internal",
    )


def judge_faithfulness(question: str, ans: str, sources: list) -> float:
    if not sources:
        return 0.0
    evidence = "\n".join(f"[{s['index']}] {s['excerpt']}" for s in sources)
    eval_prompt = (
        "You are a strict RAG faithfulness evaluator. Given Evidence and an Answer, "
        "return a score from 0.0 to 1.0 indicating whether every factual claim in the Answer "
        "is directly supported by the Evidence (1.0 = completely faithful, 0.0 = hallucinated/refused). "
        "Output ONLY the numeric score.\n\n"
        f"Evidence:\n{evidence}\n\nQuestion: {question}\nAnswer: {ans}"
    )
    try:
        cfg = settings()
        options = {"region_name": cfg.aws_region}
        if cfg.aws_access_key_id and cfg.aws_secret_access_key:
            options.update(
                aws_access_key_id=cfg.aws_access_key_id,
                aws_secret_access_key=cfg.aws_secret_access_key,
            )
        client = boto3.client("bedrock-runtime", **options)
        resp = client.converse(
            modelId=cfg.bedrock_chat_model,
            messages=[{"role": "user", "content": [{"text": eval_prompt}]}],
            inferenceConfig={"temperature": 0.0, "maxTokens": 16},
        )
        raw = resp["output"]["message"]["content"][0]["text"]
        match = re.search(r"\b(1(?:\.0+)?|0(?:\.\d+)?)\b", raw)
        return float(match.group(1)) if match else 0.0
    except Exception:
        return 0.0


def run_benchmark(dataset_path: str, output_path: str):
    dataset = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    active_principal = get_benchmark_principal()
    records = []

    for item in dataset:
        t0 = time.perf_counter()
        res = chat(active_principal, item["question"], history=item.get("history", []))
        latency_ms = (time.perf_counter() - t0) * 1000.0

        ans = res.get("answer", "")
        sources = res.get("sources", [])
        status = res.get("status", "")

        if item["answerable"]:
            hit_rank = None
            for idx, s in enumerate(sources, start=1):
                excerpt = s.get("excerpt", "").lower()
                if any(kw.lower() in excerpt for kw in item["expected_keywords"]):
                    hit_rank = idx
                    break

            kw_hits = sum(
                1 for kw in item["expected_keywords"] if kw.lower() in ans.lower()
            )
            kw_recall = kw_hits / max(len(item["expected_keywords"]), 1)
            faithfulness = judge_faithfulness(item["question"], ans, sources)
            refused_ok = None
        else:
            hit_rank = None
            kw_recall = None
            faithfulness = None
            refused_phrases = (
                "could not find",
                "cannot find",
                "does not contain",
                "not mentioned",
                "does not establish",
            )
            refused_ok = status == "no_evidence" or any(
                p in ans.lower() for p in refused_phrases
            )

        records.append({
            "id": item["id"],
            "category": item["category"],
            "latency_ms": round(latency_ms, 1),
            "hit_rank": hit_rank,
            "keyword_recall": kw_recall,
            "faithfulness": faithfulness,
            "refused_correctly": refused_ok,
            "num_sources": len(sources),
            "answer_preview": ans[:160],
        })

    answerable = [r for r in records if r["keyword_recall"] is not None]
    unanswerable = [r for r in records if r["refused_correctly"] is not None]
    latencies = sorted(r["latency_ms"] for r in records)

    summary = {
        "total_cases": len(records),
        "recall_at_5_pct": round(
            sum(1 for r in answerable if r["hit_rank"] and r["hit_rank"] <= 5)
            / max(len(answerable), 1) * 100,
            2,
        ),
        "mrr": round(
            statistics.mean(
                (1.0 / r["hit_rank"]) if r["hit_rank"] else 0.0 for r in answerable
            ),
            4,
        ),
        "fact_recall_pct": round(
            statistics.mean(r["keyword_recall"] for r in answerable) * 100, 2
        ),
        "faithfulness_pct": round(
            statistics.mean(r["faithfulness"] for r in answerable) * 100, 2
        ),
        "refusal_accuracy_pct": round(
            sum(1 for r in unanswerable if r["refused_correctly"])
            / max(len(unanswerable), 1) * 100,
            2,
        ),
        "p50_latency_ms": round(statistics.median(latencies), 1),
        "p95_latency_ms": round(latencies[int(0.95 * (len(latencies) - 1))], 1),
    }

    Path(output_path).write_text(
        json.dumps({"summary": summary, "records": records}, indent=2)
    )
    print("\n=== BENCHMARK SUMMARY ===")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="test/eval_dataset.json")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    run_benchmark(args.dataset, args.out)
