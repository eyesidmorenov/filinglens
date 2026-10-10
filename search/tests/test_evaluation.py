import json
from collections import Counter
from pathlib import Path

from haystack import Document
from src.evaluation import evaluate, load_questions, summarize
from src.retrieval import RetrievalResult

QUESTIONS = Path(__file__).resolve().parents[1] / "evaluation" / "questions.json"
EXPECTED_TICKERS = {
    "AAPL", "ADBE", "ADSK", "AMGN", "ATVI", "CMCSA", "CTSH", "DXCM",
    "EA", "EBAY", "FB", "GILD", "IDXX", "ILMN", "KLAC", "LRCX", "MAR",
    "MDLZ", "NVDA", "ORLY", "PAYX", "QCOM", "SBUX", "TXN", "VRTX",
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


def test_question_set_has_exactly_75_unique_in_scope_questions():
    questions = load_questions(QUESTIONS)
    assert [question.id for question in questions] == [
        f"Q{i:02d}" for i in range(1, 76)
    ]
    assert {question.ticker for question in questions} == EXPECTED_TICKERS
    assert {question.fiscal_year for question in questions} == {2019, 2020, 2021}
    assert set(Counter(question.ticker for question in questions).values()) == {3}
    assert Counter(question.fiscal_year for question in questions) == {
        2019: 25,
        2020: 25,
        2021: 25,
    }
    assert Counter(question.category for question in questions)["numeric_results"] == 25
    assert sum(
        question.category in {"legal_proceedings", "market_risk", "controls"}
        for question in questions
    ) == 25
    assert all(question.relevant_chunk_ids == () for question in questions)


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
