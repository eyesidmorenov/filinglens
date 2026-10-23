"""No Elasticsearch, Claude or RAGAS calls: sampling, the test set, the answer record, the summary and the files."""

import json
from types import SimpleNamespace

from ragas_eval import answers, common, score, testset

QUESTIONS = [
    {"id": f"Q{i:02d}", "question": f"q{i}", "ticker": "AAPL", "fiscal_year": 2019, "category": c}
    for i, c in enumerate(["business", "risk", "numeric", "business", "risk", "numeric", "business"], 1)
]


def test_sample_spreads_over_categories_and_keeps_file_order():
    chosen = common.sample(QUESTIONS, 3)
    assert sorted(q["category"] for q in chosen) == ["business", "numeric", "risk"]
    assert common.sample(QUESTIONS, 3) == chosen  # always the same questions
    # second round: business (Q04), then numeric (Q06); categories go in alphabetical order
    assert [q["id"] for q in common.sample(QUESTIONS, 5)] == ["Q01", "Q02", "Q03", "Q04", "Q06"]


def test_sample_zero_or_more_than_all_is_all():
    assert common.sample(QUESTIONS, 0) == QUESTIONS
    assert common.sample(QUESTIONS, 99) == QUESTIONS


class FakePipeline:
    def __init__(self, message=None, status="answered"):
        self.message, self.status = message, status

    def resolve_company_year(self, question, ticker=None, fiscal_year=None):
        return (None, None, self.message) if self.message else (ticker or "AAPL", fiscal_year or 2019, None)

    def retrieve(self, question, ticker, year):
        return [{"chunk_id": "AAPL_2019_10K_p4_c2", "text": "Apple designs iPhone.", "company": "Apple Inc.",
                 "fiscal_year": 2019, "section": "Item 1", "page": 4}]

    def get_generator(self):
        result = SimpleNamespace(status=SimpleNamespace(value=self.status), answer="Apple designs iPhone [1].",
                                 sources=[object()], usage={"input_tokens": 100, "output_tokens": 20})
        return SimpleNamespace(run=lambda question, documents: result)


def test_answer_keeps_the_full_chunks_claude_saw():
    record = answers.answer_one(FakePipeline(), QUESTIONS[0])
    assert record["status"] == "answered"
    # with its source, as Claude reads it, so the judge can check "According to its fiscal 2019 10-K"
    assert record["contexts"] == ["Source: Apple Inc., fiscal 2019 10-K, Item 1, page 4\nApple designs iPhone."]
    assert record["chunk_ids"] == ["AAPL_2019_10K_p4_c2"]
    assert record["detected"] == record["expected"] == {"ticker": "AAPL", "fiscal_year": 2019}


def test_a_question_the_api_cannot_place_is_not_sent_to_claude():
    record = answers.answer_one(FakePipeline(message="Please mention one of our companies."), QUESTIONS[0])
    assert record["status"] == "not_detected"
    assert score.to_score([record]) == []


def test_only_answered_records_are_scored():
    records = [answers.answer_one(FakePipeline(status=s), QUESTIONS[0]) for s in ("answered", "out_of_scope")]
    assert [r["status"] for r in score.to_score(records)] == ["answered"]


def test_summary_averages_only_the_values_the_judge_returned():
    records = [answers.answer_one(FakePipeline(), q) for q in QUESTIONS[:2]]
    scored = [
        {"id": "Q01", "category": "business", "faithfulness": 1.0, "answer_relevancy": 0.8, "context_precision": None},
        {"id": "Q02", "category": "risk", "faithfulness": 0.5, "answer_relevancy": 0.6, "context_precision": 1.0},
    ]
    summary = score.summarize(records, scored)
    assert summary["average"] == {"faithfulness": 0.75, "answer_relevancy": 0.7, "context_precision": 1.0}
    assert summary["status"] == {"answered": 2}
    assert summary["company_and_year_detected_as_labeled"] == 2
    assert summary["answer_tokens"] == {"input": 200, "output": 40}
    assert summary["by_category"]["risk"]["n"] == 1


def test_clean_turns_a_failed_judge_call_into_none():
    assert score.clean(float("nan")) is None
    assert score.clean("0.91234") == 0.9123


def test_latest_run_and_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert common.latest_run() is None
    for name in ("2026-10-21_1600", "2026-10-21_1700"):
        run = tmp_path / "eval" / "ragas" / name
        run.mkdir(parents=True)
        (run / "answers.jsonl").write_text(json.dumps({"id": "Q01"}) + "\n", encoding="utf-8")
    run = common.latest_run()
    assert run.name == "2026-10-21_1700"
    assert score.load_answers(run / "answers.jsonl") == [{"id": "Q01"}]

    score.write_outputs(run, [{"id": "Q01", "category": "business", "faithfulness": 1.0}], {"scored": 1})
    assert (run / "scores.csv").read_text(encoding="utf-8").splitlines()[0] == \
        "id,category,faithfulness,answer_relevancy,context_precision,question"
    assert json.loads((run / "summary.json").read_text(encoding="utf-8")) == {"scored": 1}


def test_step_two_without_a_key_or_answers_says_what_to_do(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert score.main([]) == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert score.main([]) == 1
    assert "run step 1 first" in capsys.readouterr().err


def test_filings_spread_over_companies_with_years_taking_turns():
    doc_ids = [f"{t}_{y}_10K" for t in ("AAPL", "MSFT", "NVDA", "TSLA") for y in (2019, 2020, 2021)]
    assert testset.pick_filings(doc_ids, 2) == ["AAPL_2019_10K", "NVDA_2020_10K"]
    assert testset.pick_filings(doc_ids, 9) == ["AAPL_2019_10K", "MSFT_2020_10K", "NVDA_2021_10K", "TSLA_2019_10K"]


def test_chunks_come_from_the_key_sections_and_say_enough():
    text = " ".join(["word"] * testset.MIN_WORDS)
    chunks = [{"chunk_id": f"c{i}", "section": "Item 7", "text": text} for i in range(10)]
    chunks += [{"chunk_id": "exhibits", "section": "Item 15", "text": text},
               {"chunk_id": "short", "section": "Item 1A", "text": "Too short."}]
    assert [c["chunk_id"] for c in testset.pick_chunks(chunks, 5)] == ["c0", "c2", "c4", "c6", "c8"]
    assert len(testset.pick_chunks(chunks, 50)) == 10


def test_each_ragas_question_is_traced_to_its_filing():
    docs = [SimpleNamespace(page_content="Apple designs iPhone. Revenue grew 5%.",
                            metadata={"chunk_id": "AAPL_2020_10K_p4_c2", "ticker": "AAPL", "fiscal_year": 2020,
                                      "section": "Item 1", "company_name": "Apple Inc."})]
    rows = [
        {"user_input": "What does the Company design?", "reference": "iPhone.",
         "reference_contexts": ["Apple designs iPhone."]},
        {"user_input": "Something else?", "reference": "", "reference_contexts": ["Text of no chunk."]},
    ]
    traced, untraced = testset.to_questions(rows, docs)
    assert traced["id"] == "G01"
    assert (traced["ticker"], traced["fiscal_year"], traced["category"]) == ("AAPL", 2020, "Item 1")
    assert traced["source_chunk_id"] == "AAPL_2020_10K_p4_c2"
    assert untraced["ticker"] is None  # step 1 leaves it out: its company and year are unknown


def test_a_ragas_question_goes_with_its_filing_and_keeps_its_reference():
    q = {"id": "G01", "question": "What did the Company release?", "ticker": "MSFT", "fiscal_year": 2021,
         "category": "Item 1", "reference": "Surface devices."}
    record = answers.answer_one(FakePipeline(), q, given_company_year=True)
    assert record["detected"] == {"ticker": "MSFT", "fiscal_year": 2021}
    assert record["reference"] == "Surface devices."


def test_ragas_columns_take_our_metric_names():
    assert score.our_name("factual_correctness(mode=f1)") == "factual_correctness"
    assert score.our_name("llm_context_precision_with_reference") == "context_precision"
    assert score.our_name("context_recall") == "context_recall"
    assert score.our_name("user_input") is None
    assert score.metric_columns([{"faithfulness": 1.0, "context_recall": 0.5}]) == score.METRICS_WITH_REFERENCE
    assert score.metric_columns([{"faithfulness": 1.0}]) == score.METRICS_WITHOUT_REFERENCE


def test_a_yahoo_snapshot_keeps_its_fetch_date_as_source():
    hit = {"chunk_id": "yahoo-AAPL-2023", "text": "- Total revenue: 383.3B", "company": "Apple Inc.",
           "fiscal_year": 2023, "section": "Yahoo Finance (fetched on 2026-10-20)", "page": 0}
    assert answers.as_claude_saw(hit).splitlines()[0] == \
        "Source: Apple Inc., fiscal 2023, Yahoo Finance (fetched on 2026-10-20)"
