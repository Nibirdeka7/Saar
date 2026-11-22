from typing import Any, TypedDict
from langgraph.graph import END, START, StateGraph

from app.aws import answer
from app.guardrails import check_input, check_output
from app.observability import trace
from app.rag import (
    hybrid_retrieve_and_recover,
    refine_passages,
    rerank_passages,
    rewrite_queries,
)


class State(TypedDict, total=False):
    question: str
    queries: list
    principal: Any
    candidates: list
    passages: list
    answer: str
    sources: list
    status: str
    history: list


@trace("guard")
def guard(s: State):
    return {"question": check_input(s["question"])}


@trace("rewrite")
def rewrite(s: State):
    return {"queries": rewrite_queries(s["question"], s.get("history", []))}


@trace("retrieve")
def retrieve(s: State):
    candidates = hybrid_retrieve_and_recover(
        s["principal"], s.get("queries", [s["question"]])
    )
    return {"candidates": candidates}


@trace("rerank")
def rerank(s: State):
    ranked = rerank_passages(s["question"], s.get("candidates", []))
    selected, sources = refine_passages(ranked)
    return {"passages": selected, "sources": sources}


def route(s: State):
    return "generate" if s.get("passages") else "no_evidence"


@trace("no_evidence")
def no_evidence(s: State):
    return {
        "answer": "I could not find supporting evidence in documents you are authorized to access.",
        "status": "no_evidence",
    }


@trace("generate")
def generate(s: State):
    evidence = "\n\n".join(
        f"[{i + 1}] {h['metadata'].get('title', 'Document')} (Page {h['metadata'].get('page', 1)}"
        f"{', Section: ' + h['metadata']['section'] if h['metadata'].get('section') else ''}):\n"
        f"{h['metadata'].get('text', '')}"
        for i, h in enumerate(s["passages"])
    )
    return {
        "answer": answer(s["question"], evidence, s.get("history", [])),
        "status": "answered",
    }


@trace("validate")
def validate(s: State):
    return {"answer": check_output(s["answer"])}


def make_graph():
    g = StateGraph(State)
    for name, fn in [
        ("guard", guard),
        ("rewrite", rewrite),
        ("retrieve", retrieve),
        ("rerank", rerank),
        ("no_evidence", no_evidence),
        ("generate", generate),
        ("validate", validate),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "guard")
    g.add_edge("guard", "rewrite")
    g.add_edge("rewrite", "retrieve")
    g.add_edge("retrieve", "rerank")
    g.add_conditional_edges(
        "rerank", route, {"generate": "generate", "no_evidence": "no_evidence"}
    )
    g.add_edge("generate", "validate")
    g.add_edge("validate", END)
    g.add_edge("no_evidence", END)
    return g.compile()


graph = make_graph()


@trace("chat")
def chat(p, question, history=None):
    r = graph.invoke(
        {"principal": p, "question": question, "history": history or []}
    )
    return {
        "answer": r["answer"],
        "sources": r.get("sources", []),
        "status": r.get("status", "answered"),
    }
