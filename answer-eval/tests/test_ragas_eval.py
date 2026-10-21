"""No Elasticsearch, Claude or RAGAS calls: sampling, the answer record, the summary and the files."""

import json
from types import SimpleNamespace

from ragas_eval import answers, common, score

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

    def resolve_company_year(self, question):
        return (None, None, self.message) if self.message else ("AAPL", 2019, None)

    def retrieve(self, question, ticker, year):
        return [{"chunk_id": "AAPL_2019_10K_p4_c2", "text": "Apple designs iPhone."}]

    def get_generator(self):
        result = SimpleNamespace(status=SimpleNamespace(value=self.status), answer="Apple designs iPhone [1].",
                                 sources=[object()], usage={"input_tokens": 100, "output_tokens": 20})
        return SimpleNamespace(run=lambda question, documents: result)


def test_answer_keeps_the_full_chunks_claude_saw():
    record = answers.answer_one(FakePipeline(), QUESTIONS[0])
    assert record["status"] == "answered"
    assert record["contexts"] == ["Apple designs iPhone."]
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
