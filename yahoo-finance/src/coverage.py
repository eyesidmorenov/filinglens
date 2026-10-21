"""
Yahoo Finance coverage check and snapshots for the companies in the index.

For each company in the index it reads the annual income statement, balance sheet and
cash flow statement through yfinance, and writes:

    data/yahoo/coverage.csv           one row per company: status, years, key figures found
    data/yahoo/snapshots/<TICKER>.json  the key annual figures by fiscal year, with the date they were fetched

The chat never calls Yahoo live: the API reads the snapshots (they are the cache).
Analyst ratings and price targets are never read: the chatbot must not recommend investments.

The companies come from the index, not from a list kept by hand: data/chunks/_stats.csv
(one row per 10-K, written by the ETL) and the first chunk of each filing (S3 folder and
official name). Adding companies to the index adds them here, with no file to edit.
overrides.csv only holds the exceptions: a different Yahoo ticker (FB is META) and notes.

Fiscal years follow the 10-K, not the calendar. Yahoo labels each column with the
date the fiscal year ended, and companies name their years differently: NVIDIA's
fiscal 2021 ended on 2021-01-31, but Dollar Tree's fiscal 2019 ended on 2020-02-01.
Each company's rule is chosen from its own 10-Ks (choose_rule); a company whose
10-Ks fit no rule is left out and reported, so the API answers "I don't have that year"
instead of showing another year's figures. --check-fiscal-years lists the rules without
calling Yahoo.

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
OVERRIDES = HERE / "overrides.csv"
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
    company_name: str = ""  # official name from the 10-K cover, as in the index


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


def choose_rule(filings: list[tuple[int, date]]) -> str | None:
    """The rule that gives every 10-K's own fiscal year from the date it ended, or None.

    `filings` are (fiscal year in the 10-K, date its fiscal year ended). The plain rule is
    tried first: 47 of the first 50 companies use it.
    """
    for rule in FISCAL_YEAR_RULES:
        if all(fiscal_year(end, rule) == year for year, end in filings):
            return rule
    return None


def load_overrides(path: Path = OVERRIDES) -> dict[str, dict[str, str]]:
    """Exceptions by 10-K ticker: ticker_yahoo, fiscal_year_rule and note, all optional."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8", newline="") as f:
        return {r["ticker_10k"].strip().upper(): r for r in csv.DictReader(f)}


def _first_chunk(chunks_dir: Path, doc_id: str) -> dict[str, Any]:
    path = chunks_dir / f"{doc_id}.jsonl"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        line = f.readline()
    return json.loads(line) if line.strip() else {}


def companies_from_index(chunks_dir: Path, overrides: Path = OVERRIDES) -> tuple[list[TickerRow], list[str]]:
    """The companies to check, read from the ETL output, and the problems found.

    chunks_dir is data/chunks: _stats.csv gives each 10-K's fiscal year and the date it
    ended; the first chunk of each filing gives its S3 folder and official name.
    """
    stats = chunks_dir / "_stats.csv"
    if not stats.exists():
        raise FileNotFoundError(
            f"{stats} not found: load the chunk package (or run the ETL) first, "
            "the companies come from the index"
        )
    with open(stats, encoding="utf-8", newline="") as f:
        filings = list(csv.DictReader(f))
    by_ticker: dict[str, list[dict[str, str]]] = {}
    for filing in filings:
        by_ticker.setdefault(filing["doc_id"].split("_")[0], []).append(filing)
    exceptions = load_overrides(overrides)

    rows, problems = [], []
    for ticker, own in sorted(by_ticker.items()):
        extra = exceptions.get(ticker, {})
        dated = [(int(f["fiscal_year"]), date.fromisoformat(f["fiscal_year_end"])) for f in own if f.get("fiscal_year_end")]
        rule = (extra.get("fiscal_year_rule") or "").strip() or None
        if rule and rule not in FISCAL_YEAR_RULES:
            problems.append(f"{ticker}: unknown fiscal_year_rule {rule!r} in {overrides.name}; left out")
            continue
        if rule and not all(fiscal_year(end, rule) == year for year, end in dated):
            problems.append(f"{ticker}: rule {rule} in {overrides.name} does not match its 10-Ks; left out")
            continue
        if not dated:
            rule = rule or "end_year"
            problems.append(f"{ticker}: no 10-K with a fiscal year end date; {rule} assumed")
        rule = rule or choose_rule(dated)
        if rule is None:
            ends = ", ".join(f"{year} ended {end}" for year, end in dated)
            problems.append(f"{ticker}: no rule gives the fiscal years of its 10-Ks ({ends}); left out")
            continue
        chunk = _first_chunk(chunks_dir, own[0]["doc_id"])
        rows.append(TickerRow(
            ticker_10k=ticker,
            ticker_yahoo=(extra.get("ticker_yahoo") or "").strip() or ticker,
            company=chunk.get("company", ""),
            note=(extra.get("note") or "").strip(),
            fiscal_year_rule=rule,
            company_name=chunk.get("company_name", ""),
        ))
    return rows, problems


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
        "company_name": result.row.company_name,
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check what Yahoo Finance has for the FilingLens companies")
    ap.add_argument("--overrides", type=Path, default=OVERRIDES,
                    help="CSV with the exceptions: ticker_10k,ticker_yahoo,fiscal_year_rule,note")
    ap.add_argument("--out", type=Path, default=None, help="output folder (default: data/yahoo)")
    ap.add_argument("--limit", type=int, default=None, help="only the first N companies, for a quick test")
    ap.add_argument("--sleep", type=float, default=1.0, help="seconds between companies, to be gentle with Yahoo")
    ap.add_argument("--check-fiscal-years", action="store_true",
                    help="only list the companies of the index and the fiscal year rule chosen from their 10-Ks; "
                         "no call to Yahoo")
    args = ap.parse_args(argv)

    chunks_dir = data_dir() / "chunks"
    try:
        rows, problems = companies_from_index(chunks_dir, args.overrides)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    for problem in problems:
        print(f"  {problem}")

    if args.check_fiscal_years:
        by_rule: dict[str, list[str]] = {}
        for row in rows:
            by_rule.setdefault(row.fiscal_year_rule, []).append(row.ticker_10k)
        for rule, tickers in sorted(by_rule.items()):
            shown = " ".join(tickers) if len(tickers) <= 10 else f"{len(tickers)} companies"
            print(f"  {rule:<12} {shown}")
        print(f"{len(rows)} companies in the index, each with the rule that matches its 10-Ks ({chunks_dir})")
        return 1 if any("left out" in problem for problem in problems) else 0

    import yfinance as yf  # imported here so the tests never need the network

    rows = rows[: args.limit]
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
