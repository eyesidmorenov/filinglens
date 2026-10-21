"""Coverage check with fake tickers: no network, no Yahoo."""

import csv
import json
from datetime import date

import pandas as pd
import pytest

from src import coverage
from src.coverage import (
    TickerRow, check_ticker, choose_rule, companies_from_index, fiscal_year, load_overrides, write_outputs,
)


def statement(rows: dict[str, list], ends: list[str]) -> pd.DataFrame:
    """A statement shaped like yfinance's: one row per item, one column per fiscal year end."""
    return pd.DataFrame(rows, index=pd.to_datetime(ends)).T


class FakeTicker:
    def __init__(self, income=None, balance=None, cash=None, info=None, info_error=False):
        self.income_stmt = income if income is not None else pd.DataFrame()
        self.balance_sheet = balance if balance is not None else pd.DataFrame()
        self.cashflow = cash if cash is not None else pd.DataFrame()
        self._info = info or {}
        self._info_error = info_error

    @property
    def info(self):
        if self._info_error:
            raise RuntimeError("info endpoint down")
        return self._info


APPLE_ENDS = ["2025-09-30", "2024-09-30", "2023-09-30", "2022-09-30", "2021-09-30"]
NAN = float("nan")


def apple() -> FakeTicker:
    return FakeTicker(
        income=statement(
            {"Total Revenue": [416.0, 391.0, 383.0, 394.0, NAN],
             "Net Income": [112.0, 94.0, 97.0, 100.0, NAN],
             "Gross Profit": [195.0, 180.0, 169.0, 171.0, NAN],
             "Operating Income": [133.0, 123.0, 114.0, 119.0, NAN]},
            APPLE_ENDS,
        ),
        balance=statement({"Total Assets": [359.0, 365.0, 353.0, 353.0, NAN]}, APPLE_ENDS),
        cash=statement({"Free Cash Flow": [99.0, 109.0, 100.0, 111.0, NAN]}, APPLE_ENDS),
        info={"longName": "Apple Inc.", "financialCurrency": "USD"},
    )


ROW = TickerRow("AAPL", "AAPL", "apple-inc")


def test_years_skip_the_almost_empty_oldest_column():
    result = check_ticker(ROW, lambda symbol: apple())
    assert result.status == "ok"
    assert result.years["income_stmt"] == [2022, 2023, 2024, 2025]
    assert result.latest_year == 2025
    assert result.name_on_yahoo == "Apple Inc."
    assert result.currency == "USD"
    assert result.figures["Total Revenue"]["2024"] == 391.0
    assert result.period_end["2024"] == "2024-09-30"


def test_missing_rows_are_reported_not_invented():
    result = check_ticker(ROW, lambda symbol: apple())
    missing = result.missing_figures()
    assert "Total Debt" in missing and "Operating Cash Flow" in missing
    assert "Total Revenue" not in missing


def test_a_delisted_company_is_no_data():
    result = check_ticker(TickerRow("ATVI", "ATVI", "activision-blizzard-inc"), lambda symbol: FakeTicker())
    assert result.status == "no_data"
    assert result.latest_year is None


def test_a_failing_ticker_is_an_error_and_does_not_raise():
    def boom(symbol):
        raise ConnectionError("Yahoo blocked the request")

    result = check_ticker(ROW, boom)
    assert result.status == "error"
    assert "ConnectionError" in result.error


def test_a_broken_info_endpoint_keeps_the_figures():
    fake = apple()
    fake._info_error = True
    result = check_ticker(ROW, lambda symbol: fake)
    assert result.status == "ok"
    assert result.name_on_yahoo == ""
    assert result.currency == ""


def test_outputs_csv_and_snapshot(tmp_path):
    ok = check_ticker(ROW, lambda symbol: apple())
    empty = check_ticker(TickerRow("ATVI", "ATVI", "activision-blizzard-inc", "acquired"), lambda s: FakeTicker())
    path = write_outputs([ok, empty], tmp_path, "2026-10-12T22:00:00Z")

    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    assert [r["status"] for r in rows] == ["ok", "no_data"]
    assert rows[0]["years_after_2021"] == "2022 2023 2024 2025"
    assert rows[1]["note"] == "acquired"

    snap = json.loads((tmp_path / "snapshots" / "AAPL.json").read_text(encoding="utf-8"))
    assert snap["fetched_at"] == "2026-10-12T22:00:00Z"
    assert snap["source"].startswith("Yahoo Finance")
    assert snap["fiscal_year_rule"] == "end_year"
    assert snap["figures"]["Net Income"]["2025"] == 112.0
    assert snap["currency"] == "USD"
    assert rows[0]["currency"] == "USD"
    assert not (tmp_path / "snapshots" / "ATVI.json").exists()


def test_snapshots_never_include_analyst_ratings():
    every_row = [name for rows in coverage.KEY_ROWS.values() for name in rows]
    assert not any("recommend" in name.lower() or "target" in name.lower() for name in every_row)


def test_overrides_hold_only_the_exceptions():
    overrides = load_overrides()
    assert overrides["FB"]["ticker_yahoo"] == "META"
    assert {"ATVI", "CERN", "SPLK", "ANSS"} <= set(overrides)
    # The fiscal year rules come from the 10-Ks, not from this file
    assert not any((row.get("fiscal_year_rule") or "").strip() for row in overrides.values())


@pytest.mark.parametrize("end, rule, expected", [
    ("2021-09-25", "end_year", 2021),     # Apple
    ("2021-01-31", "end_year", 2021),     # NVIDIA: its fiscal 2021 ended in January 2021
    ("2020-02-01", "most_months", 2019),  # Dollar Tree: its fiscal 2019 ended in February 2020
    ("2023-01-31", "most_months", 2022),  # Dollar Tree as Yahoo shows it (end of month): fiscal 2022, not 2023
    ("2022-01-01", "most_months", 2021),  # Cadence, 52/53-week year
    ("2019-12-28", "most_months", 2019),  # Cadence, the same rule in a year that ends in December
])
def test_fiscal_year_follows_the_10k(end, rule, expected):
    assert fiscal_year(date.fromisoformat(end), rule) == expected


def test_snapshot_years_are_10k_fiscal_years_not_calendar_years():
    ends = ["2024-02-03", "2023-01-28", "2022-01-29"]
    dollar_tree = FakeTicker(income=statement({"Total Revenue": [30.6, 28.3, 26.3]}, ends))
    row = TickerRow("DLTR", "DLTR", "dollar-tree-inc", fiscal_year_rule="most_months")
    result = check_ticker(row, lambda symbol: dollar_tree)
    assert result.years["income_stmt"] == [2021, 2022, 2023]
    assert result.figures["Total Revenue"]["2023"] == 30.6
    assert result.period_end["2023"] == "2024-02-03"


def d(text):
    return date.fromisoformat(text)


def test_the_rule_is_chosen_from_the_10ks():
    apple = [(2019, d("2019-09-28")), (2020, d("2020-09-26")), (2021, d("2021-09-25"))]
    nvidia = [(2021, d("2021-01-31"))]
    dollar_tree = [(2019, d("2020-02-01")), (2020, d("2021-01-30")), (2021, d("2022-01-29"))]
    cadence = [(2019, d("2019-12-28")), (2020, d("2021-01-02")), (2021, d("2022-01-01"))]
    contradictory = [(2019, d("2019-12-31")), (2021, d("2020-12-31"))]
    assert choose_rule(apple) == "end_year"
    assert choose_rule(nvidia) == "end_year"
    assert choose_rule(dollar_tree) == "most_months"
    assert choose_rule(cadence) == "most_months"
    assert choose_rule(contradictory) is None


def index_fixture(tmp_path, overrides_text="ticker_10k,ticker_yahoo,fiscal_year_rule,note\n"):
    chunks = tmp_path / "chunks"
    chunks.mkdir()
    (chunks / "_stats.csv").write_text(
        "doc_id,fiscal_year,fiscal_year_end\n"
        "AAPL_2019_10K,2019,2019-09-28\n"
        "AAPL_2020_10K,2020,2020-09-26\n"
        "DLTR_2019_10K,2019,2020-02-01\n"
        "DLTR_2020_10K,2020,2021-01-30\n"
        "FB_2021_10K,2021,2021-12-31\n"
        "ATVI_2020_10K,2020,\n"
        "ODD_2019_10K,2019,2019-12-31\n"
        "ODD_2020_10K,2021,2020-12-31\n",
        encoding="utf-8",
    )
    first = {"company": "apple-inc", "company_name": "Apple Inc.", "text": "Apple"}
    (chunks / "AAPL_2019_10K.jsonl").write_text(json.dumps(first) + "\n", encoding="utf-8")
    overrides = tmp_path / "overrides.csv"
    overrides.write_text(overrides_text, encoding="utf-8")
    return chunks, overrides


def test_companies_come_from_the_index_with_their_rules(tmp_path):
    chunks, overrides = index_fixture(
        tmp_path, "ticker_10k,ticker_yahoo,fiscal_year_rule,note\nFB,META,,Ticker changed\n"
    )
    rows, problems = companies_from_index(chunks, overrides)
    by_10k = {row.ticker_10k: row for row in rows}
    # A new company in the index needs no file edit: it is here, with the rule of its 10-Ks
    assert set(by_10k) == {"AAPL", "ATVI", "DLTR", "FB"}
    assert by_10k["AAPL"].fiscal_year_rule == "end_year"
    assert (by_10k["AAPL"].company, by_10k["AAPL"].company_name) == ("apple-inc", "Apple Inc.")
    assert by_10k["DLTR"].fiscal_year_rule == "most_months"
    assert (by_10k["FB"].ticker_yahoo, by_10k["FB"].note) == ("META", "Ticker changed")
    # No end date: the plain rule is assumed and said; 10-Ks that fit no rule: left out, not guessed
    assert any(p.startswith("ATVI") and "assumed" in p for p in problems)
    assert any(p.startswith("ODD") and "left out" in p for p in problems)


def test_an_override_that_contradicts_the_10ks_is_rejected(tmp_path):
    chunks, overrides = index_fixture(
        tmp_path, "ticker_10k,ticker_yahoo,fiscal_year_rule,note\nDLTR,,end_year,\n"
    )
    rows, problems = companies_from_index(chunks, overrides)
    assert "DLTR" not in {row.ticker_10k for row in rows}
    assert any(p.startswith("DLTR") and "does not match" in p for p in problems)


def test_without_the_index_it_says_what_to_load(tmp_path):
    with pytest.raises(FileNotFoundError, match="chunk package"):
        companies_from_index(tmp_path / "chunks")


@pytest.mark.parametrize("value, expected", [(1.5, 1.5), ("2", 2.0), (NAN, None), (None, None), ("n/a", None)])
def test_number(value, expected):
    assert coverage._number(value) == expected
