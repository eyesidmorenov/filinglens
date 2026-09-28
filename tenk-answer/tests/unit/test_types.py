from __future__ import annotations

from typing import Any

import jsonschema
import pytest
from haystack import Document

from tenk_answer import Answer, AnswerStatus, InvalidDocumentError, SearchResult, Source

CONTRACT3_KEYS = {"chunk_id", "text", "score", "section", "page", "company", "fiscal_year"}


def test_search_result_document_round_trip_is_lossless(results: dict[str, SearchResult]) -> None:
    for result in results.values():
        doc = result.to_document()
        assert doc.id == result.chunk_id
        assert doc.content == result.text
        assert doc.score == result.score
        assert doc.meta == {
            "section": result.section,
            "page": result.page,
            "company": result.company,
            "fiscal_year": result.fiscal_year,
        }
        assert SearchResult.from_document(doc) == result


def test_search_result_dump_matches_contract3(raw_results: dict[str, dict[str, Any]]) -> None:
    for raw in raw_results.values():
        assert SearchResult.from_dict(raw).model_dump() == raw


@pytest.mark.parametrize("missing", sorted(CONTRACT3_KEYS))
def test_missing_contract3_field_raises(raw_results: dict[str, dict[str, Any]], missing: str) -> None:
    raw = dict(next(iter(raw_results.values())))
    del raw[missing]
    with pytest.raises(InvalidDocumentError):
        SearchResult.from_dict(raw)


@pytest.mark.parametrize("missing", ["section", "page", "company", "fiscal_year"])
def test_document_missing_meta_raises(results: dict[str, SearchResult], missing: str) -> None:
    doc = next(iter(results.values())).to_document()
    del doc.meta[missing]
    with pytest.raises(InvalidDocumentError, match=missing):
        SearchResult.from_document(doc)


def test_document_without_score_or_content_raises() -> None:
    meta = {"section": "Item 7", "page": 1, "company": "X", "fiscal_year": 2024}
    with pytest.raises(InvalidDocumentError):
        SearchResult.from_document(Document(id="X_1", content="text", meta=meta))
    with pytest.raises(InvalidDocumentError):
        SearchResult.from_document(Document(id="X_1", content=None, score=0.5, meta=meta))


def _answer() -> Answer:
    return Answer(
        status=AnswerStatus.ANSWERED,
        answer="Revenue was $391,035 million.",
        sources=[
            Source(
                company="Apple Inc.",
                fiscal_year=2024,
                section="Item 7",
                page=21,
                excerpt="Total net sales were $391,035 million",
                chunk_id="AAPL_2024_10K_p21_c1",
            )
        ],
        latency_ms=1840,
        model="claude-fake",
        usage={"input_tokens": 1},
    )


def test_to_api_response_matches_contract4_exactly(contract4_schema: dict[str, Any]) -> None:
    response = _answer().to_api_response()
    assert response == {
        "answer": "Revenue was $391,035 million.",
        "sources": [
            {
                "company": "Apple Inc.",
                "fiscal_year": 2024,
                "section": "Item 7",
                "page": 21,
                "excerpt": "Total net sales were $391,035 million",
            }
        ],
        "latency_ms": 1840,
    }
    jsonschema.validate(response, contract4_schema)


def test_to_api_response_leaks_no_internal_fields(contract4_schema: dict[str, Any]) -> None:
    response = _answer().to_api_response()
    assert set(response) == {"answer", "sources", "latency_ms"}
    flat = repr(response)
    for leaked in ("status", "chunk_id", "model", "usage", "claude-fake", "AAPL_2024_10K_p21_c1"):
        assert leaked not in flat
    empty = Answer(status=AnswerStatus.OUT_OF_SCOPE, answer="No.").to_api_response()
    jsonschema.validate(empty, contract4_schema)
