"""
Downloads a deterministic sample of filings from S3.

Deterministic means it always downloads exactly the same files, no matter
who runs it or when. That way the whole team works with the same sample
and the results are comparable.

It never downloads again what is already on disk, so it can be run as
many times as needed without wasting transfer.

Usage:
    python download_sample.py                                  # base sample, 5 companies
    python download_sample.py --check                          # only checks, downloads nothing
    python download_sample.py --companies eda/companies.csv    # companies from a list
"""

import argparse
import csv
import os
import re
import sys
from pathlib import Path

import boto3
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

BUCKET = "anyoneai-datasets"
PREFIX = "nasdaq_annual_reports/"

# Output folder, relative to the project root
DESTINATION = Path(__file__).parent.parent / "data" / "raw"
# The file name is a data contract: the ETL reads data/raw/inventario.csv
INVENTORY = DESTINATION / "inventario.csv"

# --- The sample. Fixed on purpose. ---
# The project scope is these three years: the dataset ends in 2021.
YEARS = [2019, 2020, 2021]

# S3 folder -> expected ticker
COMPANIES = {
    "apple-inc": "AAPL",
    "nvidia-corporation": "NVDA",
    "microsoft-corporation": "MSFT",
    "tesla-inc": "TSLA",
    "intel-corporation": "INTC",
}

# Files to always ignore
IGNORE = {".DS_Store"}


def get_client():
    key = os.getenv("AWS_ACCESS_KEY_ID")
    secret = os.getenv("AWS_SECRET_ACCESS_KEY")
    if not key or not secret:
        print("ERROR: missing credentials. Check that eda/.env exists with the keys.")
        sys.exit(1)
    return boto3.client(
        "s3",
        aws_access_key_id=key,
        aws_secret_access_key=secret,
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )


# NASDAQ_AAPL_2019.pdf, and the variant with a hash suffix found in 45 files:
# NASDAQ_ICUI_2016_be053643da474abb9e048daf1ac9aa5f.pdf
# Same pattern used by explore_s3.py.
FILE_NAME = re.compile(
    r"^(?P<exchange>[A-Za-z]+)_(?P<ticker>[^_/]+)_(?P<year>\d{4})"
    r"(?:_(?P<suffix>[0-9a-f]{32}))?\.pdf$",
    re.IGNORECASE,
)


def list_company(client, folder):
    """
    Lists the files of one company. Returns {year: (key, size)}.

    If a year appears twice (the same file uploaded with and without a hash),
    it keeps the one without the hash, and if both have it, the first one in
    alphabetical order. That way the choice is always the same.
    """
    candidates = {}
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=f"{PREFIX}{folder}/"):
        for obj in page.get("Contents", []):
            name = obj["Key"].split("/")[-1]
            if name in IGNORE:
                continue
            m = FILE_NAME.match(name)
            if not m:
                continue
            year = int(m["year"])
            if 1990 <= year <= 2025:
                candidates.setdefault(year, []).append(
                    (m["suffix"] is not None, obj["Key"], obj["Size"])
                )

    found = {}
    for year, options in candidates.items():
        options.sort()
        if len(options) > 1:
            print(f"      note: {folder} {year} has {len(options)} files, using {options[0][1].split('/')[-1]}")
        _, key, size = options[0]
        found[year] = (key, size)
    return found


def parse_metadata(key):
    """Gets company, exchange, ticker and year from the path. Without opening the PDF."""
    parts = key.split("/")
    m = FILE_NAME.match(parts[-1])
    if not m:
        return None
    return {
        "company": parts[-2],
        "exchange": m["exchange"].upper(),
        "ticker": m["ticker"].upper(),
        "year": int(m["year"]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="only check coverage, download nothing")
    ap.add_argument("--companies", type=Path,
                    help="CSV with columns company,ticker (e.g. eda/companies.csv). Without it, uses the 5-company sample")
    args = ap.parse_args()

    global COMPANIES
    if args.companies:
        with open(args.companies, encoding="utf-8") as f:
            COMPANIES = {row["company"]: row["ticker"] for row in csv.DictReader(f)}
        print(f"Companies read from {args.companies}")

    client = get_client()
    DESTINATION.mkdir(parents=True, exist_ok=True)

    print(f"Sample: {len(COMPANIES)} companies x {len(YEARS)} years = "
          f"{len(COMPANIES) * len(YEARS)} expected documents")
    print(f"Destination: {DESTINATION}\n")

    plan = []     # what we will download
    missing = []  # what does not exist in the bucket

    # --- 1. Check coverage before downloading anything ---
    print("Checking coverage...")
    for folder, expected_ticker in COMPANIES.items():
        available = list_company(client, folder)
        if not available:
            print(f"  {folder:<28} NOT FOUND in the bucket")
            missing.extend((folder, y, "company does not exist") for y in YEARS)
            continue

        present = [y for y in YEARS if y in available]
        absent = [y for y in YEARS if y not in available]

        status = "complete" if not absent else f"missing {absent}"
        others = sorted(set(available) - set(YEARS))
        extra = f"  (also has {others})" if others else ""
        print(f"  {folder:<28} {len(present)}/{len(YEARS)} {status}{extra}")

        for year in present:
            key, size = available[year]
            meta = parse_metadata(key)
            if not meta:
                print(f"      unparseable name: {key}")
                continue
            if meta["ticker"] != expected_ticker:
                print(f"      note: ticker {meta['ticker']} != expected {expected_ticker}")
            plan.append({**meta, "key": key, "size": size})
        for year in absent:
            missing.append((folder, year, "year not available"))

    print(f"\nAvailable to download: {len(plan)}")
    if missing:
        print(f"Missing: {len(missing)}")
        for c, y, reason in missing:
            print(f"  {c} {y}: {reason}")

    if args.check:
        print("\n--check mode: nothing was downloaded.")
        return

    # --- 2. Download what is not on disk yet ---
    print("\nDownloading...")
    rows, downloaded, skipped = [], 0, 0
    for item in plan:
        local = DESTINATION / f"{item['ticker']}_{item['year']}.pdf"
        if local.exists() and local.stat().st_size == item["size"]:
            skipped += 1
        else:
            client.download_file(BUCKET, item["key"], str(local))
            downloaded += 1
            print(f"  {local.name:<20} {item['size'] / 1024**2:6.1f} MB")

        rows.append({
            "doc_id": f"{item['ticker']}_{item['year']}_10K",
            "company": item["company"],
            "ticker": item["ticker"],
            "fiscal_year": item["year"],
            "exchange": item["exchange"],
            "s3_key": item["key"],
            "local_path": f"data/raw/{local.name}",
            "size_mb": round(item["size"] / 1024**2, 2),
        })

    # --- 3. Inventory ---
    rows.sort(key=lambda r: (r["ticker"], r["fiscal_year"]))
    with open(INVENTORY, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    total_mb = sum(r["size_mb"] for r in rows)
    print(f"\nDownloaded now: {downloaded}   already there: {skipped}")
    print(f"Total on disk: {len(rows)} documents, {total_mb:.1f} MB")
    print(f"Inventory: {INVENTORY}")
    print("\nDone. Text extraction can start from data/raw/")


if __name__ == "__main__":
    main()
