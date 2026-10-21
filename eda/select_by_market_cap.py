"""
Picks the candidate companies for the third batch (from 50 to 100 companies), by market value.

The first two batches came from the Nasdaq-100 of 2019-2021 (select_companies.py), and that
list is used up: of its names with the three years in the bucket, only Atlassian is left, and
it files a 20-F, not a 10-K. So this batch takes, among the bucket companies with 2019, 2020
and 2021, the largest by market value today, as Yahoo Finance reports it. It is a criterion
anyone can check, and it favours well-known companies with complete, readable filings.

A company counts only if Yahoo lists it as a stock on NASDAQ, based in the United States
(foreign companies usually file a 20-F, which the ETL skips), with a market value. Companies
already tried in a batch, or already in the index, are left out. It picks more candidates than
needed on purpose: about 70% pass the ETL (25 of 35 in batch 2).

Input:   data/eda/bucket_inventory.csv (from explore_s3.py; no S3 calls here)
Cache:   data/eda/market_caps.csv (one row per ticker asked; a second run only asks the missing ones)
Output:  eda/companies_batch3.csv   (versioned in Git: the list is a project decision)

Usage (yfinance comes with the yahoo image), from the repository root:
    docker compose --profile yahoo run --rm -v ./eda:/app/eda yahoo python eda/select_by_market_cap.py
    ... python eda/select_by_market_cap.py --n 70
"""

import argparse
import csv
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("DATA_DIR", ROOT / "data"))
INVENTORY = DATA / "eda" / "bucket_inventory.csv"
CACHE = DATA / "eda" / "market_caps.csv"
OUTPUT = Path(__file__).parent / "companies_batch3.csv"
PREVIOUS = [Path(__file__).parent / "companies.csv", Path(__file__).parent / "companies_batch2.csv"]
STATS = DATA / "chunks" / "_stats.csv"
YEARS = {2019, 2020, 2021}
NASDAQ = {"NMS", "NGM", "NCM"}  # Yahoo's codes for the three NASDAQ market tiers
CACHE_COLUMNS = ["ticker", "market_cap", "exchange", "quote_type", "country", "name", "fetched_at", "error"]


def complete_companies(inventory: Path) -> dict[str, dict]:
    """Companies with the three fiscal years in the bucket: their tickers and 2019-2021 size."""
    years, tickers, size = defaultdict(set), defaultdict(set), defaultdict(float)
    with open(inventory, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            year = int(row["fiscal_year"])
            if year in YEARS:
                years[row["company"]].add(year)
                tickers[row["company"]].add(row["ticker"].upper())
                size[row["company"]] += float(row["size_mb"])
    return {c: {"tickers": sorted(tickers[c]), "size_mb": round(size[c], 1)} for c in years if YEARS <= years[c]}


def already_used() -> tuple[set[str], set[str]]:
    """Companies (S3 folders) and tickers tried in earlier batches or already in the index."""
    companies, tickers = set(), set()
    for path in PREVIOUS:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    companies.add(row["company"])
                    tickers.add(row["ticker"].upper())
    if STATS.exists():
        with open(STATS, encoding="utf-8") as f:
            tickers.update(row["doc_id"].split("_")[0] for row in csv.DictReader(f))
    return companies, tickers


def load_cache(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return {row["ticker"]: row for row in csv.DictReader(f)}


def save_cache(path: Path, cache: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CACHE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(cache[t] for t in sorted(cache))


def ask_yahoo(ticker: str, make_ticker) -> dict:
    """Market value and listing of one ticker. Never raises: a failure is kept in `error`."""
    row = {"ticker": ticker, "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    try:
        info = make_ticker(ticker).info or {}
    except Exception as exc:  # noqa: BLE001 - one bad ticker must not stop the run
        return {**row, "error": f"{type(exc).__name__}: {exc}"[:200]}
    return {
        **row,
        "market_cap": info.get("marketCap") or "",
        "exchange": info.get("exchange") or "",
        "quote_type": info.get("quoteType") or "",
        "country": info.get("country") or "",
        "name": info.get("longName") or info.get("shortName") or "",
        "error": "",
    }


def eligible(row: dict) -> bool:
    """A US stock listed on NASDAQ today, with a market value."""
    return (
        not row.get("error")
        and row.get("quote_type") == "EQUITY"
        and row.get("exchange") in NASDAQ
        and row.get("country") == "United States"
        and bool(row.get("market_cap"))
    )


def rank(companies: dict[str, dict], cache: dict[str, dict]) -> list[tuple[str, str, float]]:
    """(company, ticker, market cap) for the eligible companies, largest first."""
    ranked = []
    for company, info in companies.items():
        best = max(
            ((t, float(cache[t]["market_cap"])) for t in info["tickers"] if t in cache and eligible(cache[t])),
            key=lambda pair: pair[1],
            default=None,
        )
        if best:
            ranked.append((company, best[0], best[1]))
    return sorted(ranked, key=lambda r: (-r[2], r[0]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--n", type=int, default=70, help="how many candidates to pick")
    ap.add_argument("--sleep", type=float, default=0.5, help="seconds between Yahoo calls")
    args = ap.parse_args()

    if not INVENTORY.exists():
        raise SystemExit(f"Can't find {INVENTORY}. Run first: python eda/explore_s3.py")
    companies = complete_companies(INVENTORY)
    used_companies, used_tickers = already_used()
    candidates = {
        c: info for c, info in companies.items()
        if c not in used_companies and not set(info["tickers"]) & used_tickers
    }
    tickers = sorted({t for info in candidates.values() for t in info["tickers"]})

    cache = load_cache(CACHE)
    missing = [t for t in tickers if t not in cache or cache[t].get("error")]
    print(f"With the three years 2019-2021: {len(companies):,}; not tried yet: {len(candidates):,}")
    print(f"Tickers to ask Yahoo: {len(missing):,} (already in {CACHE.name}: {len(tickers) - len(missing):,})")
    if missing:
        import yfinance as yf  # imported here: ranking from the cache needs no network

        for i, ticker in enumerate(missing, 1):
            cache[ticker] = ask_yahoo(ticker, yf.Ticker)
            if i % 25 == 0 or i == len(missing):
                save_cache(CACHE, cache)
                errors = sum(1 for t in missing[:i] if cache[t].get("error"))
                print(f"  {i:>5}/{len(missing)} asked, {errors} errors", flush=True)
            time.sleep(args.sleep)

    ranked = rank(candidates, cache)
    chosen = ranked[: args.n]
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["rank", "company", "ticker", "size_mb_2019_2021", "market_cap_usd_bn", "name_on_yahoo"])
        for i, (company, ticker, cap) in enumerate(chosen, 1):
            writer.writerow([i, company, ticker, candidates[company]["size_mb"], round(cap / 1e9, 1), cache[ticker]["name"]])

    errors = sum(1 for t in tickers if cache.get(t, {}).get("error"))
    print(f"\nEligible (US stock on NASDAQ with a market value): {len(ranked):,}")
    print(f"Candidates saved to {OUTPUT.relative_to(ROOT)}: {len(chosen)}")
    for i, (company, ticker, cap) in enumerate(chosen, 1):
        print(f"  {i:>2}. {ticker:<6} {cap / 1e9:>8.1f} bn  {company}")
    if errors:
        print(f"\nNote: {errors} tickers failed (kept in {CACHE.name}); run again to retry them.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
