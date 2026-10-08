"""
Picks the candidate companies to move from the sample to 25 companies.

It reads the inventory already measured by explore_s3.py (no S3 calls) and keeps
the companies that have the three years in scope, 2019, 2020 and 2021, prioritizing
the best-known NASDAQ names. It picks more than 25 on purpose: the ETL drops the
ones without a 10-K (as happened with Microsoft), and we keep the first 25 that pass.

Input:   data/eda/bucket_inventory.csv
Output:  eda/companies.csv   (versioned in Git: the list is a project decision)

Usage:
    python eda/select_companies.py              # 35 candidates
    python eda/select_companies.py --n 30
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INVENTORY = ROOT / "data" / "eda" / "bucket_inventory.csv"
OUTPUT = Path(__file__).parent / "companies.csv"

YEARS = {2019, 2020, 2021}

# Well-known NASDAQ companies, in priority order (Nasdaq-100 members in those years).
# US companies only: foreign ones (ASML, JD, Baidu...) file a 20-F, not a 10-K.
KNOWN = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "GOOG", "FB", "META", "TSLA", "NVDA", "INTC",
    "PYPL", "ADBE", "NFLX", "CSCO", "CMCSA", "PEP", "COST", "AVGO", "QCOM", "TXN",
    "AMD", "AMGN", "SBUX", "INTU", "TMUS", "ISRG", "BKNG", "GILD", "MDLZ", "MU",
    "AMAT", "ADP", "CHTR", "LRCX", "FISV", "CSX", "ATVI", "ADSK", "ILMN", "VRTX",
    "REGN", "MRNA", "ZM", "EBAY", "KLAC", "MAR", "IDXX", "CTSH", "EA", "ROST",
    "ORLY", "LULU", "PAYX", "MNST", "DXCM", "ALGN", "WBA", "EXC", "XEL", "CTAS",
    "BIIB", "SNPS", "CDNS", "MRVL", "FAST", "VRSK", "PCAR", "ANSS", "CPRT", "DLTR",
    "SWKS", "INCY", "MCHP", "KHC", "AEP", "DOCU", "OKTA", "CRWD", "WDAY", "TEAM",
    "ZS", "DDOG", "FTNT", "PTON", "SIRI", "CERN", "MELI",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=35, help="how many candidates to pick")
    args = ap.parse_args()

    if not INVENTORY.exists():
        raise SystemExit(f"Can't find {INVENTORY.relative_to(ROOT)}. Run first: python eda/explore_s3.py")

    years = defaultdict(set)
    tickers = defaultdict(set)
    size = defaultdict(float)
    with open(INVENTORY, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            year = int(row["fiscal_year"])
            if year in YEARS:
                years[row["company"]].add(year)
                tickers[row["company"]].add(row["ticker"].upper())
                size[row["company"]] += float(row["size_mb"])

    complete = [c for c in years if YEARS <= years[c]]
    priority = {t: i for i, t in enumerate(KNOWN)}

    def rank(company):
        return min((priority[t] for t in tickers[company] if t in priority), default=None)

    known = sorted((c for c in complete if rank(c) is not None), key=lambda c: (rank(c), c))
    chosen = known[: args.n]

    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["rank", "company", "ticker", "size_mb_2019_2021"])
        for i, c in enumerate(chosen, 1):
            ticker = next(t for t in sorted(tickers[c]) if t in priority)
            w.writerow([i, c, ticker, round(size[c], 1)])

    print(f"Companies in the inventory:             {len(years):,}")
    print(f"With the three years 2019, 2020, 2021:  {len(complete):,}")
    print(f"Of those, well-known NASDAQ names:      {len(known):,}")
    print(f"Candidates saved to {OUTPUT.relative_to(ROOT)}: {len(chosen)}")
    for i, c in enumerate(chosen, 1):
        print(f"  {i:>2}. {c:<36} {', '.join(sorted(tickers[c]))}")
    if len(chosen) < args.n:
        print(f"\nNote: there are only {len(chosen)} well-known candidates with the three years.")


if __name__ == "__main__":
    main()
