import json

from src.labels import main, relevant_chunk_ids


def _chunk(identifier, section, text, page=10):
    return {"chunk_id": identifier, "section": section, "page": page, "text": text}


def _question(qid, category, sections):
    return {"id": qid, "category": category, "expected_sections": sections}


def test_a_figure_counts_only_next_to_its_metric():
    chunks = [
        _chunk("statement", "Item 8", "Table (Item 8): INCOME\n| Total net sales | 274,515 | 260,174 |"),
        _chunk("other_row", "Item 8", "Table (Item 8): LEASES\n| Lease payments | 274,515 |"),
        _chunk("sentence", "Item 7", "Net income was 57,411 in 2020. Other items were small."),
    ]
    question = _question("Q02", "numeric_results", ["Item 8", "Item 7"])
    assert relevant_chunk_ids(question, chunks) == ["statement", "sentence"]


def test_controls_need_the_conclusion():
    chunks = [
        _chunk("definition", "Item 9A", "Disclosure controls are designed to ensure..."),
        _chunk("conclusion", "Item 9A", "Our CEO and CFO believe that our disclosure controls were effective."),
    ]
    question = _question("Q26", "controls", ["Item 9A"])
    assert relevant_chunk_ids(question, chunks) == ["conclusion"]


def test_broader_questions_need_two_of_their_topics():
    chunks = [
        _chunk("two", "Item 1A", "We face intense competition, and our cloud services may fail."),
        _chunk("one", "Item 1A", "We face intense competition."),
        _chunk("wrong_section", "Item 7", "Competition and cloud services."),
    ]
    question = _question("Q05", "risk_factors", ["Item 1A"])
    assert relevant_chunk_ids(question, chunks) == ["two"]


def test_short_sections_take_every_chunk_within_the_known_pages():
    chunks = [
        _chunk("real_7a", "Item 7A", "Interest Rate Sensitivity", page=40),
        _chunk("statements", "Item 7A", "CONSOLIDATED BALANCE SHEETS", page=46),
    ]
    assert relevant_chunk_ids(_question("Q40", "market_risk", ["Item 7A"]), chunks) == ["real_7a"]
    assert relevant_chunk_ids(_question("Q13", "market_risk", ["Item 7A"]), chunks) == ["real_7a", "statements"]


def test_main_refuses_to_write_when_a_question_has_no_evidence(tmp_path):
    questions = tmp_path / "questions.json"
    original = [{"id": "Q03", "ticker": "AAPL", "fiscal_year": 2021, "category": "legal_proceedings",
                 "expected_sections": ["Item 3"], "relevant_chunk_ids": []}]
    questions.write_text(json.dumps(original), encoding="utf-8")
    chunks = tmp_path / "chunks"
    chunks.mkdir()
    (chunks / "AAPL_2021_10K.jsonl").write_text(
        json.dumps(_chunk("AAPL_2021_10K_p20_c1", "Item 1A", "Risks")) + "\n", encoding="utf-8"
    )

    assert main(["--questions", str(questions), "--chunks", str(chunks)]) == 1
    assert json.loads(questions.read_text(encoding="utf-8")) == original
