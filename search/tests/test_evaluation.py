import copy
import json
from collections import Counter
from pathlib import Path

import pytest
from haystack import Document
from src.evaluation import evaluate, load_questions, summarize
from src.retrieval import RetrievalResult

QUESTIONS = Path(__file__).resolve().parents[1] / "evaluation" / "questions.json"
EXPECTED_TICKERS = {
    "AAPL", "ADBE", "ADSK", "AMGN", "ATVI", "CMCSA", "CTSH", "DXCM",
    "EA", "EBAY", "FB", "GILD", "IDXX", "ILMN", "KLAC", "LRCX", "MAR",
    "MDLZ", "NVDA", "ORLY", "PAYX", "QCOM", "SBUX", "TXN", "VRTX",
    # added on 2026-10-16
    "AAL", "ADI", "ANSS", "BIIB", "CDNS", "CERN", "CTAS", "DDOG", "DLTR",
    "ENPH", "FAST", "INCY", "KHC", "LOGI", "NDAQ", "NTAP", "OKTA", "SNPS",
    "SPLK", "STX", "TSCO", "UAL", "WDC", "WYNN", "XEL",
}


def _doc(identifier, ticker, year, section):
    return Document(
        id=identifier,
        content="evidence",
        score=1.0,
        meta={
            "ticker": ticker,
            "fiscal_year": year,
            "section": section,
            "page": 1,
            "company": "company",
        },
    )


def test_question_set_has_exactly_150_unique_in_scope_questions():
    questions = load_questions(QUESTIONS, expected_count=150)
    assert [question.id for question in questions] == [
        f"Q{i:02d}" for i in range(1, 151)
    ]
    assert {question.ticker for question in questions} == EXPECTED_TICKERS
    assert {question.fiscal_year for question in questions} == {2019, 2020, 2021}
    assert set(Counter(question.ticker for question in questions).values()) == {3}
    assert Counter(question.fiscal_year for question in questions) == {
        2019: 50,
        2020: 50,
        2021: 50,
    }
    assert Counter(question.category for question in questions)["numeric_results"] == 50
    assert sum(
        question.category in {"legal_proceedings", "market_risk", "controls"}
        for question in questions
    ) == 50
    # Exact labels (src/labels.py): evidence chunks from each question's own filing
    for question in questions:
        prefix = f"{question.ticker}_{question.fiscal_year}_10K_p"
        assert question.relevant_chunk_ids, question.id
        assert all(chunk_id.startswith(prefix) for chunk_id in question.relevant_chunk_ids)


def test_question_loader_accepts_a_150_question_set_without_code_changes(tmp_path):
    template = json.loads(QUESTIONS.read_text(encoding="utf-8"))[0]
    raw = []
    for number in range(1, 151):
        item = copy.deepcopy(template)
        item["id"] = f"Q{number:03d}"
        raw.append(item)

    path = tmp_path / "questions-150.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert len(load_questions(path)) == 150
    with pytest.raises(ValueError, match="expected 75 questions, found 150"):
        load_questions(path, expected_count=75)


def test_question_loader_rejects_an_empty_set(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="at least one question"):
        load_questions(path)


class FakeRetriever:
    def run(self, question, ticker, fiscal_year):
        hit = _doc("hit", ticker, fiscal_year, "Item 1A")
        miss = _doc("miss", ticker, fiscal_year, "Item 8")
        return RetrievalResult(bm25=[miss, hit], vector=[hit], hybrid=[hit, miss])


def test_evaluation_compares_all_three_modes(tmp_path):
    raw = json.loads(QUESTIONS.read_text(encoding="utf-8"))[:1]
    raw[0]["expected_sections"] = ["Item 1A"]
    raw[0]["relevant_chunk_ids"] = ["hit"]
    path = tmp_path / "one.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    questions = load_questions(path, expected_count=1)

    report = evaluate(questions, FakeRetriever())

    assert report["question_count"] == 1
    assert report["metrics"]["bm25"]["exact_mrr_at_k"] == 0.5
    assert report["metrics"]["vector"]["exact_mrr_at_k"] == 1.0
    assert report["metrics"]["hybrid"]["section_hit_rate_at_k"] == 1.0
    assert report["metrics"]["hybrid"]["filter_compliance_rate"] == 1.0
    assert report["breakdowns"]["ticker"]["AAPL"]["question_count"] == 1
    assert (
        report["breakdowns"]["category"][raw[0]["category"]]["metrics"]["hybrid"]
        ["exact_hit_rate_at_k"]
        == 1.0
    )
    assert report["diagnostics"]["hybrid"] == {
        "error_ids": [],
        "empty_result_ids": [],
        "filter_failure_ids": [],
        "section_miss_ids": [],
        "exact_miss_ids": [],
    }


def test_diagnostics_expose_exact_and_section_misses(tmp_path):
    raw = json.loads(QUESTIONS.read_text(encoding="utf-8"))[:1]
    raw[0]["expected_sections"] = ["Item 7A"]
    raw[0]["relevant_chunk_ids"] = ["not-returned"]
    path = tmp_path / "one-miss.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    report = evaluate(load_questions(path, expected_count=1), FakeRetriever())

    assert report["diagnostics"]["hybrid"]["section_miss_ids"] == [raw[0]["id"]]
    assert report["diagnostics"]["hybrid"]["exact_miss_ids"] == [raw[0]["id"]]


def test_unlabeled_exact_metrics_are_not_fabricated():
    records = [
        {
            "error": None,
            "has_exact_labels": False,
            "modes": {
                "hybrid": {
                    "result_count": 1,
                    "filters_match": True,
                    "section_rank": 1,
                    "exact_rank": None,
                }
            },
        }
    ]
    metrics = summarize(records, "hybrid")
    assert metrics["exact_labeled_questions"] == 0
    assert metrics["exact_hit_rate_at_k"] is None
    assert metrics["exact_mrr_at_k"] is None
