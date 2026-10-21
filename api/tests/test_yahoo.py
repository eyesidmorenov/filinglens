"""Yahoo Finance snapshots answer the fiscal years after the 10-Ks (agreed on 2026-10-20).

No Yahoo, Elasticsearch or Claude: the snapshots are small JSON files in a temporary folder.
"""

import json

import pytest

from app import pipeline, yahoo

APPLE = {
    "ticker_10k": "AAPL",
    "ticker_yahoo": "AAPL",
    "company": "apple-inc",
    "currency": "USD",
    "source": "Yahoo Finance (via yfinance)",
    "fetched_at": "2026-10-20T14:03:11Z",
    "fiscal_year_end": {"2023": "2023-09-30", "2024": "2024-09-28"},
    "figures": {
        "Total Revenue": {"2023": 383285000000, "2024": 391035000000},
        "Net Income": {"2023": 96995000000, "2024": None},
    },
}


@pytest.fixture(autouse=True)
def snapshots(tmp_path, monkeypatch):
    folder = tmp_path / "snapshots"
    folder.mkdir()
    (folder / "AAPL.json").write_text(json.dumps(APPLE), encoding="utf-8")
    monkeypatch.setattr(yahoo, "YAHOO_DIR", tmp_path)
    return tmp_path


def test_years_skip_empty_values():
    assert yahoo.years("AAPL") == (2023, 2024)
    assert yahoo.years("NVDA") == ()  # no snapshot


def test_chunk_is_contract_3_with_page_0():
    chunk = yahoo.chunk("AAPL", 2023, "Apple Inc.")
    assert chunk["section"] == "Yahoo Finance (fetched on 2026-10-20)"
    assert chunk["page"] == 0
    assert chunk["company"] == "Apple Inc."
    assert chunk["fiscal_year"] == 2023
    assert "- Total Revenue: 383,285,000,000 USD (about 383.3 billion)" in chunk["text"]
    assert "- Net Income: 96,995,000,000 USD" in chunk["text"]
    assert "not from the company's 10-K" in chunk["text"]


def test_chunk_leaves_out_missing_figures():
    text = yahoo.chunk("AAPL", 2024, "Apple Inc.")["text"]
    assert "Total Revenue" in text
    assert "Net Income" not in text
    assert yahoo.chunk("AAPL", 2019, "Apple Inc.") is None


@pytest.mark.parametrize("ticker", ["../AAPL", "aapl/../../etc", "", "AAPL.json/x"])
def test_only_plain_tickers_name_a_file(ticker):
    assert yahoo.load_snapshot(ticker) is None


def test_a_yahoo_year_is_accepted():
    assert pipeline.resolve_company_year("What was Apple's revenue in 2023?") == ("AAPL", 2023, None)


def test_a_year_with_no_data_says_what_we_have():
    ticker, year, message = pipeline.resolve_company_year("What was Apple's revenue in 2015?")
    assert (ticker, year) == (None, None)
    assert message.startswith("I don't have fiscal 2015 for Apple Inc.")
    assert "2019 to 2021 from its 10-K filings" in message
    assert "2023 and 2024 from Yahoo Finance" in message


def test_without_snapshot_the_message_only_names_the_10ks():
    _, _, message = pipeline.resolve_company_year("What was NVIDIA's revenue in 2023?")
    assert message.startswith("I don't have fiscal 2023 for NVIDIA Corporation.")
    assert message.endswith("from its 10-K filings.")


def test_index_years_still_use_the_10ks(monkeypatch):
    monkeypatch.setattr(pipeline, "search", lambda q, t, y: [{"chunk_id": "10k"}])
    assert pipeline.retrieve("revenue?", "AAPL", 2021) == [{"chunk_id": "10k"}]


def test_later_years_use_the_snapshot(monkeypatch):
    monkeypatch.setattr(pipeline, "search", lambda q, t, y: pytest.fail("no 10-K search for 2023"))
    [chunk] = pipeline.retrieve("revenue?", "AAPL", 2023)
    assert chunk["chunk_id"] == "yahoo-AAPL-2023"
    assert chunk["company"] == "Apple Inc."
