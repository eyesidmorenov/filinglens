import sys
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.company_year import (
    analyze_company_year,
    clarification_message,
    extract_company_year,
    supported_tickers,
    supported_years,
)
from app import pipeline


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Apple risk factors 2019", ("AAPL", 2019)),
        ("AAPL total net sales in FY2021", ("AAPL", 2021)),
        ("What did $NVDA report in FY 2020?", ("NVDA", 2020)),
        ("Adobe revenue for fiscal 2019", ("ADBE", 2019)),
        ("Facebook legal proceedings in 2019", ("FB", 2019)),
        ("What did Meta Platforms report in 2021?", ("FB", 2021)),
        ("Electronic Arts net income during fiscal year 2020", ("EA", 2020)),
        ("O’Reilly Automotive revenue in 2021", ("ORLY", 2021)),
        ("Mondelez results in 2019", ("MDLZ", 2019)),
    ],
)
def test_extracts_supported_company_and_year(question, expected):
    assert extract_company_year(question) == expected


def test_company_without_year_is_returned_partially():
    assert extract_company_year("What risks did NVIDIA identify?") == ("NVDA", None)


def test_year_without_company_is_returned_partially():
    assert extract_company_year("What happened in fiscal 2020?") == (None, 2020)


def test_multiple_companies_are_ambiguous_but_keep_the_year():
    match = analyze_company_year("Compare Apple and NVIDIA in 2021")
    assert match.ticker is None
    assert match.fiscal_year == 2021
    assert match.company_candidates == ("AAPL", "NVDA")
    assert match.company_is_ambiguous


def test_multiple_years_are_ambiguous_but_keep_the_company():
    match = analyze_company_year("Compare Apple's results in 2019 and 2021")
    assert match.ticker == "AAPL"
    assert match.fiscal_year is None
    assert match.year_candidates == (2019, 2021)
    assert match.year_is_ambiguous


def test_aliases_for_the_same_company_are_not_ambiguous():
    match = analyze_company_year("Did Facebook or Meta report this in 2021?")
    assert match.company_candidates == ("FB",)
    assert (match.ticker, match.fiscal_year) == ("FB", 2021)


def test_short_tickers_do_not_match_inside_ordinary_words():
    assert extract_company_year("How did earnings and market risk change in 2020?") == (None, 2020)


def test_bare_lowercase_short_tickers_are_not_assumed():
    assert extract_company_year("What happened to ea in 2020?") == (None, 2020)
    assert extract_company_year("What happened in mar 2020?") == (None, 2020)


def test_dollar_prefixed_lowercase_ticker_is_not_assumed():
    assert extract_company_year("What did $nvda report in 2020?") == (None, 2020)


def test_explicit_uppercase_short_tickers_are_supported():
    assert extract_company_year("EA revenue 2019") == ("EA", 2019)
    assert extract_company_year("FB revenue 2020") == ("FB", 2020)
    assert extract_company_year("MAR revenue 2021") == ("MAR", 2021)


def test_unsupported_year_is_not_silently_changed():
    match = analyze_company_year("Apple revenue in 2022")
    assert (match.ticker, match.fiscal_year) == ("AAPL", 2022)
    assert match.year_candidates == (2022,)
    assert "outside the supported range" in clarification_message(match)


def test_out_of_scope_company_is_none_but_year_is_preserved():
    assert extract_company_year("Tesla revenue in 2021") == (None, 2021)
    assert extract_company_year("Tesla revenue in 2022") == (None, 2022)


def test_company_names_match_complete_words_only():
    assert extract_company_year("Meta revenue 2021") == ("FB", 2021)
    assert extract_company_year("Metaverse revenue 2021") == (None, 2021)
    assert extract_company_year("Metadata controls 2021") == (None, 2021)


def test_clarification_identifies_the_missing_dimension():
    company_only = analyze_company_year("Apple risks")
    year_only = analyze_company_year("Risks in 2020")
    assert clarification_message(company_only) == "Please specify a fiscal year: 2019, 2020, or 2021."
    assert clarification_message(year_only) == "Please mention one of the 25 supported NASDAQ companies."


def test_clarification_explains_ambiguity():
    match = analyze_company_year("Compare Apple 2019 with NVIDIA 2021")
    message = clarification_message(match)
    assert "more than one company" in message
    assert "more than one year" in message


def test_explicit_api_fields_can_complete_a_partial_question():
    match = analyze_company_year("What were the risk factors?")
    assert clarification_message(match, ticker="AAPL", fiscal_year=2019) == ""


def test_catalog_matches_the_agreed_scope():
    # The fixture catalog holds the first 25 companies (tests/conftest.py)
    assert len(supported_tickers()) == 25
    assert supported_years() == (2019, 2020, 2021)
    assert {"AAPL", "ADBE", "FB", "NVDA", "VRTX"} <= supported_tickers()


def test_non_string_question_is_rejected():
    with pytest.raises(TypeError, match="question must be a string"):
        analyze_company_year(None)  # type: ignore[arg-type]


def test_clarification_rejects_an_explicit_unsupported_ticker():
    match = analyze_company_year("Revenue in 2021")
    assert clarification_message(match, ticker="TSLA", fiscal_year=2021) == (
        "Please mention one of the 25 supported NASDAQ companies."
    )


@pytest.mark.parametrize(
    ("question", "expected_message"),
    [
        ("What are Apple's risks?", "Please specify a fiscal year: 2019, 2020, or 2021."),
        ("What happened in 2020?", "Please mention one of the 25 supported NASDAQ companies."),
        (
            "Compare Apple and NVIDIA in 2021",
            "I found more than one company; please ask about one company at a time.",
        ),
        (
            "Compare Apple's results in 2019 and 2021",
            "I found more than one year; please ask about one fiscal year at a time.",
        ),
        (
            "Apple revenue in 2022",  # no Yahoo snapshot in the tests (conftest.py)
            "I don't have fiscal 2022 for Apple Inc. I can answer about fiscal 2019 to 2021 from its 10-K filings.",
        ),
        ("Tesla revenue in 2021", "Please mention one of the 25 supported NASDAQ companies."),
    ],
)
def test_pipeline_returns_specific_clarification_without_search(
    question, expected_message, monkeypatch
):
    def unexpected_search(*args, **kwargs):
        pytest.fail("search must not run for an incomplete, ambiguous, or unsupported question")

    monkeypatch.setattr(pipeline, "search", unexpected_search)

    assert pipeline.answer_question(question) == {
        "answer": expected_message,
        "sources": [],
        "latency_ms": 0,
    }


def test_pipeline_rejects_an_explicit_unsupported_ticker_without_search(monkeypatch):
    def unexpected_search(*args, **kwargs):
        pytest.fail("search must not run for an unsupported explicit ticker")

    monkeypatch.setattr(pipeline, "search", unexpected_search)

    assert pipeline.answer_question("Revenue in 2021", ticker="TSLA", fiscal_year=2021) == {
        "answer": "Please mention one of the 25 supported NASDAQ companies.",
        "sources": [],
        "latency_ms": 0,
    }


def test_pipeline_sends_a_valid_extracted_pair_to_search(monkeypatch):
    captured = {}

    def fake_search(question, ticker, fiscal_year):
        captured.update(question=question, ticker=ticker, fiscal_year=fiscal_year)
        return [{"id": "chunk-1"}]

    def fake_generate(question, hits):
        return {"answer": "ok", "sources": hits, "latency_ms": 1}

    monkeypatch.setattr(pipeline, "search", fake_search)
    monkeypatch.setattr(pipeline, "generate", fake_generate)

    result = pipeline.answer_question("What were NVIDIA's risks in fiscal 2020?")

    assert captured == {
        "question": "What were NVIDIA's risks in fiscal 2020?",
        "ticker": "NVDA",
        "fiscal_year": 2020,
    }
    assert result == {"answer": "ok", "sources": [{"id": "chunk-1"}], "latency_ms": 1}
