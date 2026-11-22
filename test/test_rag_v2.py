import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.rag import tokenize, refine_passages, rerank_passages
from worker.ingest import clean_text, guess_section, make_chunks


def test_clean_text():
    raw = "Here is a hyphen-\nated word.   Extra    spaces.\r\n\r\nSecond paragraph."
    cleaned = clean_text(raw)
    assert "hyphenated" in cleaned
    assert "Extra spaces." in cleaned
    assert "\n\nSecond paragraph." in cleaned


def test_guess_section():
    assert guess_section("# Security Rules\nSome text") == "Security Rules"
    assert guess_section("## Policy ID: SEC-402\nDetails") == "Policy ID: SEC-402"
    assert guess_section("Random intro line") == ""


def test_tokenize():
    tokens = tokenize("What is Policy SEC-402 for AWS FIDO2 authentication?")
    assert "sec-402" in tokens
    assert "aws" in tokens
    assert "fido2" in tokens
    assert "what" not in tokens  # Stop word
    assert "is" not in tokens    # Stop word


def test_refine_passages_budgeting():
    passages = [
        {
            "metadata": {"document_id": "doc1", "title": "Doc 1", "page": 1, "section": "Sec A", "text": "A" * 5000},
            "score": 0.85
        },
        {
            "metadata": {"document_id": "doc2", "title": "Doc 2", "page": 2, "section": "Sec B", "text": "B" * 4000},
            "score": 0.75
        },
        {
            "metadata": {"document_id": "doc3", "title": "Doc 3", "page": 1, "section": "Sec C", "text": "C" * 100},
            "score": 0.10  # Below min_relevance (0.25)
        }
    ]
    selected, sources = refine_passages(passages)
    # Total chars <= 7500, so only the first 5000 chars doc should be selected
    assert len(selected) == 1
    assert len(sources) == 1
    assert sources[0]["score"] == 0.85
    assert sources[0]["title"] == "Doc 1"
    assert sources[0]["section"] == "Sec A"


def test_rerank_lexical_fallback():
    question = "AWS FIDO2 hardware MFA"
    passages = [
        {
            "metadata": {"text": "Employees receive 24 days of paid time off."},
            "rrf_score": 0.01
        },
        {
            "metadata": {"text": "All production AWS environments require hardware MFA (FIDO2/WebAuthn)."},
            "rrf_score": 0.02
        }
    ]
    ranked = rerank_passages(question, passages)
    assert len(ranked) == 2
    # The passage with AWS, FIDO2, hardware, MFA should rank first
    assert "FIDO2" in ranked[0]["metadata"]["text"]
    assert ranked[0]["score"] > ranked[1]["score"]
