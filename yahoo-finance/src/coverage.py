"""
Yahoo Finance coverage check and snapshots for the companies in the index.

For each company of tickers.csv (the 50 in the index) it reads the annual income
statement, balance sheet and cash flow statement through yfinance, and writes:

    data/yahoo/coverage.csv           one row per company: status, years, key figures found
    data/yahoo/snapshots/<TICKER>.json  the key annual figures by fiscal year, with the date they were fetched

The chat never calls Yahoo live: the API reads the snapshots (they are the cache).
Analyst ratings and price targets are never read: the chatbot must not recommend investments.

Fiscal years follow the 10-K, not the calendar. Yahoo labels each column with the
date the fiscal year ended, and companies name their years differently: NVIDIA's
fiscal 2021 ended on 2021-01-31, but Dollar Tree's fiscal 2019 ended on 2020-02-01.
Each company's rule is in tickers.csv (`fiscal_year_rule`), and --check-fiscal-years
verifies it against the 10-Ks in the index (data/chunks/_stats.csv).

Usage (from the repository root):
    docker compose --profile yahoo run --rm yahoo
    docker compose --profile yahoo run --rm yahoo python -m src.coverage --limit 3
    docker compose --profile yahoo run --rm yahoo python -m src.coverage --check-fiscal-years
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
from datetime import date, datetime, timedelta, timezone
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

# How a company names its fiscal year, from the date it ended:
#   end_year     the calendar year of the end date (Apple: ended 2021-09-25 -> fiscal 2021;
#                NVIDIA: ended 2021-01-31 -> fiscal 2021)
#   most_months  the calendar year where most of the fiscal year falls (Dollar Tree: ended
#                2020-02-01 -> fiscal 2019; Cadence: ended 2022-01-01 -> fiscal 2021)
FISCAL_YEAR_RULES = ("end_year", "most_months")

COVERAGE_COLUMNS = [
    "ticker_10k", "ticker_yahoo", "company", "status", "name_on_yahoo", "currency",
    "income_years", "balance_years", "cashflow_years", "latest_fiscal_year",
    "years_after_2021", "missing_figures", "note", "error",
]


def fiscal_year(end: date, rule: str) -> int:
    """The fiscal year a company's 10-K would give a year that ended on `end`."""
    if rule == "end_year":
        return end.year
    if rule == "most_months":
        return (end - timedelta(days=182)).year
    raise ValueError(f"unknown fiscal_year_rule {rule!r}: use one of {FISCAL_YEAR_RULES}")


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
    fiscal_year_rule: str = "end_year"


@dataclass
class Coverage:
    row: TickerRow
    # ok | no_data (delisted, wrong symbol, or Yahoo not reached) | error
    status: str = "ok"
    name_on_yahoo: str = ""
    currency: str = ""  # reporting currency of the statements, e.g. "USD"
    years: dict[str, list[int]] = field(default_factory=dict)
    figures: dict[str, dict[str, float]] = field(default_factory=dict)  # "Total Revenue" -> {fiscal year: value}
    period_end: dict[str, str] = field(default_factory=dict)  # fiscal year -> end date: "2023" -> "2023-09-30"
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
            TickerRow(
                r["ticker_10k"], r["ticker_yahoo"], r["company"], r.get("note") or "",
                r.get("fiscal_year_rule") or "end_year",
            )
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
    and one row per line item. The column becomes the fiscal year the company's 10-K would
    use (see fiscal_year). A year counts only if at least one key figure has a value
    (Yahoo sometimes adds an older column that is almost empty).

    Yahoo moves period ends to the end of the month (Apple shows 2025-09-30 for September 27),
    so the dates kept in fiscal_year_end are approximate. The fiscal year is not: both rules
    give the same year for the real date and for the end of its month (Dollar Tree's year that
    ended 2023-01-28 shows as 2023-01-31, still fiscal 2022).
    """
    if frame is None or getattr(frame, "empty", True):
        result.years[kind] = []
        return
    found_years: set[int] = set()
    for column in frame.columns:
        end = column.date() if hasattr(column, "date") else column
        label = fiscal_year(end, result.row.fiscal_year_rule)
        year = str(label)
        for name in KEY_ROWS[kind]:
            if name not in frame.index:
                continue
            value = _number(frame.at[name, column])
            if value is None:
                continue
            result.figures.setdefault(name, {})[year] = value
            result.period_end[year] = end.isoformat()
            found_years.add(label)
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
        "fiscal_year_rule": result.row.fiscal_year_rule,
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


def check_fiscal_years(rows: list[TickerRow], stats: Path) -> list[str]:
    """Problems found comparing each company's rule with its 10-Ks in the index.

    `stats` is data/chunks/_stats.csv from the ETL: one row per filing, with the fiscal year
    the 10-K uses and the date its fiscal year ended. An empty list means every rule agrees.
    """
    with open(stats, encoding="utf-8", newline="") as f:
        filings = list(csv.DictReader(f))
    problems = []
    for row in rows:
        if row.fiscal_year_rule not in FISCAL_YEAR_RULES:
            problems.append(f"{row.ticker_10k}: unknown fiscal_year_rule {row.fiscal_year_rule!r}")
            continue
        own = [f for f in filings if f["doc_id"].split("_")[0] == row.ticker_10k and f.get("fiscal_year_end")]
        if not own:
            problems.append(f"{row.ticker_10k}: no 10-K with a fiscal year end date in {stats.name}")
        for filing in own:
            expected = int(filing["fiscal_year"])
            got = fiscal_year(date.fromisoformat(filing["fiscal_year_end"]), row.fiscal_year_rule)
            if got != expected:
                problems.append(
                    f"{row.ticker_10k}: fiscal year ended {filing['fiscal_year_end']} is {expected} in the 10-K, "
                    f"but rule {row.fiscal_year_rule} gives {got}"
                )
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check what Yahoo Finance has for the FilingLens companies")
    ap.add_argument("--tickers", type=Path, default=TICKERS, help="CSV with ticker_10k,ticker_yahoo,company,note")
    ap.add_argument("--out", type=Path, default=None, help="output folder (default: data/yahoo)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N companies, for a quick test")
    ap.add_argument("--sleep", type=float, default=1.0, help="seconds between companies, to be gentle with Yahoo")
    ap.add_argument("--check-fiscal-years", action="store_true",
                    help="only compare each company's fiscal_year_rule with its 10-Ks (data/chunks/_stats.csv); "
                         "no call to Yahoo")
    args = ap.parse_args(argv)

    if args.check_fiscal_years:
        stats = data_dir() / "chunks" / "_stats.csv"
        rows = load_tickers(args.tickers)
        problems = check_fiscal_years(rows, stats)
        for problem in problems:
            print(f"  {problem}")
        wrong = {problem.split(":")[0] for problem in problems}
        print(f"{len(rows) - len(wrong)}/{len(rows)} companies: the rule matches every 10-K in {stats}")
        return 1 if problems else 0

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
