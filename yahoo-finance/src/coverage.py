"""
Yahoo Finance coverage check for the 25 FilingLens companies.

Research spike, not part of the chatbot yet. It answers one question before the
team decides anything: for each of our companies, which fiscal years and which
figures does Yahoo Finance have after the 10-Ks end (2021)?

For each ticker it reads the annual income statement, balance sheet and cash
flow statement through yfinance, and writes:

    data/yahoo/coverage.csv           one row per company: status, years, key figures found
    data/yahoo/snapshots/<TICKER>.json  the key annual figures, with the date they were fetched

The snapshots let a demo run without calling Yahoo live. Analyst ratings and
price targets are never read: the chatbot must not recommend investments.

Usage (from the repository root):
    docker compose --profile yahoo run --rm yahoo
    docker compose --profile yahoo run --rm yahoo python -m src.coverage --limit 3
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parents[1]
TICKERS = HERE / "tickers.csv"
SOURCE = "Yahoo Finance (via yfinance)"

# The figures we look for in each statement, by the row names Yahoo uses.
KEY_ROWS = {
    "income_stmt": ["Total Revenue", "Gross Profit", "Operating Income", "Net Income"],
    "balance_sheet": ["Total Assets", "Total Debt", "Stockholders Equity"],
    "cashflow": ["Operating Cash Flow", "Free Cash Flow"],
}

COVERAGE_COLUMNS = [
    "ticker_10k", "ticker_yahoo", "company", "status", "name_on_yahoo", "currency",
    "income_years", "balance_years", "cashflow_years", "latest_fiscal_year",
    "years_after_2021", "missing_figures", "note", "error",
]


def data_dir() -> Path:
    if os.environ.get("DATA_DIR"):
        return Path(os.environ["DATA_DIR"])
    return HERE.parent / "data"


@dataclass
class TickerRow:
    ticker_10k: str
    ticker_yahoo: str
    company: str
    note: str = ""


@dataclass
class Coverage:
    row: TickerRow
    # ok | no_data (delisted, wrong symbol, or Yahoo not reached) | error
    status: str = "ok"
    name_on_yahoo: str = ""
    currency: str = ""  # reporting currency of the statements, e.g. "USD"
    years: dict[str, list[int]] = field(default_factory=dict)
    figures: dict[str, dict[str, float]] = field(default_factory=dict)  # "Total Revenue" -> {"2023": ...}
    period_end: dict[str, str] = field(default_factory=dict)  # "2023" -> "2023-09-30"
    error: str = ""

    @property
    def latest_year(self) -> int | None:
        all_years = [y for ys in self.years.values() for y in ys]
        return max(all_years) if all_years else None

    def missing_figures(self) -> list[str]:
        return [name for rows in KEY_ROWS.values() for name in rows if not self.figures.get(name)]

    def to_csv_row(self) -> dict[str, Any]:
        def years(kind: str) -> str:
            return " ".join(str(y) for y in self.years.get(kind, []))

        after = sorted({y for ys in self.years.values() for y in ys if y > 2021})
        return {
            "ticker_10k": self.row.ticker_10k,
            "ticker_yahoo": self.row.ticker_yahoo,
            "company": self.row.company,
            "status": self.status,
            "name_on_yahoo": self.name_on_yahoo,
            "currency": self.currency,
            "income_years": years("income_stmt"),
            "balance_years": years("balance_sheet"),
            "cashflow_years": years("cashflow"),
            "latest_fiscal_year": self.latest_year or "",
            "years_after_2021": " ".join(str(y) for y in after),
            "missing_figures": "; ".join(self.missing_figures()) if self.status == "ok" else "",
            "note": self.row.note,
            "error": self.error,
        }


def load_tickers(path: Path = TICKERS) -> list[TickerRow]:
    with open(path, encoding="utf-8", newline="") as f:
        return [
            TickerRow(r["ticker_10k"], r["ticker_yahoo"], r["company"], r.get("note") or "")
            for r in csv.DictReader(f)
        ]


def _number(value: Any) -> float | None:
    """A statement cell as a plain float; NaN and empty cells become None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def read_statement(frame: Any, kind: str, result: Coverage) -> None:
    """Record which fiscal years a statement has, and the key figures for each year.

    yfinance returns one column per fiscal year, labelled with the period end date,
    and one row per line item. A year counts only if at least one key figure has a value
    (Yahoo sometimes adds an older column that is almost empty).

    The fiscal year is the calendar year of the period end, the same rule as the 10-K
    file names: NVIDIA's fiscal 2023 ends in January 2023. Yahoo moves period ends to the
    end of the month (Apple shows 2025-09-30 for September 27), so the dates kept in
    fiscal_year_end are approximate; the year is not.
    """
    if frame is None or getattr(frame, "empty", True):
        result.years[kind] = []
        return
    found_years: set[int] = set()
    for column in frame.columns:
        end = column.date() if hasattr(column, "date") else column
        year = str(end.year)
        for name in KEY_ROWS[kind]:
            if name not in frame.index:
                continue
            value = _number(frame.at[name, column])
            if value is None:
                continue
            result.figures.setdefault(name, {})[year] = value
            result.period_end[year] = end.isoformat()
            found_years.add(end.year)
    result.years[kind] = sorted(found_years)


def check_ticker(row: TickerRow, make_ticker: Callable[[str], Any]) -> Coverage:
    """Coverage of one company. Never raises: a failure becomes status 'error'."""
    result = Coverage(row=row)
    try:
        ticker = make_ticker(row.ticker_yahoo)
        for kind in KEY_ROWS:
            read_statement(getattr(ticker, kind), kind, result)
        try:
            info = ticker.info or {}
            result.name_on_yahoo = info.get("longName") or info.get("shortName") or ""
            # The figures are raw amounts in this currency (Apple revenue 416161000000 = USD 416.2 billion)
            result.currency = info.get("financialCurrency") or ""
        except Exception:  # noqa: BLE001 - the name is a nice-to-have
            result.name_on_yahoo = ""
            result.currency = ""
    except Exception as exc:  # noqa: BLE001 - one bad ticker must not stop the run
        result.status = "error"
        result.error = f"{type(exc).__name__}: {exc}"[:300]
        return result
    if result.latest_year is None:
        result.status = "no_data"
    return result


def snapshot(result: Coverage, fetched_at: str) -> dict[str, Any]:
    return {
        "ticker_10k": result.row.ticker_10k,
        "ticker_yahoo": result.row.ticker_yahoo,
        "company": result.row.company,
        "name_on_yahoo": result.name_on_yahoo,
        "currency": result.currency,
        "source": SOURCE,
        "fetched_at": fetched_at,
        "fiscal_year_end": dict(sorted(result.period_end.items())),
        "figures": {name: dict(sorted(values.items())) for name, values in result.figures.items()},
        "note": result.row.note,
    }


def write_outputs(results: list[Coverage], out_dir: Path, fetched_at: str) -> Path:
    snapshots = out_dir / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    for result in results:
        if result.status == "ok":
            path = snapshots / f"{result.row.ticker_10k}.json"
            path.write_text(json.dumps(snapshot(result, fetched_at), indent=2), encoding="utf-8")
    coverage = out_dir / "coverage.csv"
    with open(coverage, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COVERAGE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(r.to_csv_row() for r in results)
    return coverage


def print_summary(results: list[Coverage]) -> None:
    print(f"\n{'10-K':<6} {'Yahoo':<6} {'status':<8} {'years':<22} missing")
    for r in results:
        years = " ".join(str(y) for y in sorted({y for ys in r.years.values() for y in ys}))
        missing = r.error if r.status == "error" else "; ".join(r.missing_figures())
        print(f"{r.row.ticker_10k:<6} {r.row.ticker_yahoo:<6} {r.status:<8} {years:<22} {missing}")
    ok = sum(r.status == "ok" for r in results)
    after = sum(any(y > 2021 for ys in r.years.values() for y in ys) for r in results)
    print(f"\n{ok}/{len(results)} companies with data; {after} with fiscal years after 2021")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check what Yahoo Finance has for the 25 FilingLens companies")
    ap.add_argument("--tickers", type=Path, default=TICKERS, help="CSV with ticker_10k,ticker_yahoo,company,note")
    ap.add_argument("--out", type=Path, default=None, help="output folder (default: data/yahoo)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N companies, for a quick test")
    ap.add_argument("--sleep", type=float, default=1.0, help="seconds between companies, to be gentle with Yahoo")
    args = ap.parse_args(argv)

    import yfinance as yf  # imported here so the tests never need the network

    rows = load_tickers(args.tickers)[: args.limit]
    out_dir = args.out or data_dir() / "yahoo"
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"Checking {len(rows)} companies on {SOURCE}, yfinance {yf.__version__} -> {out_dir}")

    results = []
    for i, row in enumerate(rows):
        if i:
            time.sleep(args.sleep)
        result = check_ticker(row, yf.Ticker)
        print(f"  {row.ticker_10k:<6} {result.status}")
        results.append(result)

    coverage = write_outputs(results, out_dir, fetched_at)
    print_summary(results)
    print(f"\nSaved: {coverage} and {out_dir / 'snapshots'}")
    if not any(r.status == "ok" for r in results):
        # yfinance turns a blocked or offline request into empty tables, not an error,
        # so "no data for every company" almost always means Yahoo was not reached.
        print("\nWARNING: Yahoo returned nothing for every company. Check the internet "
              "connection (or a Yahoo block) before reading coverage.csv.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
