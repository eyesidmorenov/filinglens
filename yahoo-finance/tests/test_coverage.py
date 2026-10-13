"""Coverage check with fake tickers: no network, no Yahoo."""

import csv
import json

import pandas as pd
import pytest

from src import coverage
from src.coverage import TickerRow, check_ticker, load_tickers, write_outputs


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
        info={"longName": "Apple Inc."},
    )


ROW = TickerRow("AAPL", "AAPL", "apple-inc")


def test_years_skip_the_almost_empty_oldest_column():
    result = check_ticker(ROW, lambda symbol: apple())
    assert result.status == "ok"
    assert result.years["income_stmt"] == [2022, 2023, 2024, 2025]
    assert result.latest_year == 2025
    assert result.name_on_yahoo == "Apple Inc."
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
    assert snap["figures"]["Net Income"]["2025"] == 112.0
    assert not (tmp_path / "snapshots" / "ATVI.json").exists()


def test_snapshots_never_include_analyst_ratings():
    every_row = [name for rows in coverage.KEY_ROWS.values() for name in rows]
    assert not any("recommend" in name.lower() or "target" in name.lower() for name in every_row)


def test_ticker_list_is_the_final_25():
    rows = load_tickers()
    assert len(rows) == 25
    assert len({r.ticker_10k for r in rows}) == 25
    by_10k = {r.ticker_10k: r for r in rows}
    assert by_10k["FB"].ticker_yahoo == "META"
    assert "DXCM" in by_10k and "INTC" not in by_10k and "MSFT" not in by_10k


@pytest.mark.parametrize("value, expected", [(1.5, 1.5), ("2", 2.0), (NAN, None), (None, None), ("n/a", None)])
def test_number(value, expected):
    assert coverage._number(value) == expected
