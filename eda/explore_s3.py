"""
Explores the S3 bucket without downloading anything.

Goal: understand how the dataset is organized before deciding which
sample to download and how to extract the metadata of each document.

Outputs (so the notebook reads measured data, not copied numbers):
    data/eda/bucket_inventory.csv   one row per file, metadata parsed from the path
    data/eda/bucket_unparsed.csv    paths that do not follow the naming convention

Usage:
    python eda/explore_s3.py
"""

import csv
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

BUCKET = "anyoneai-datasets"
PREFIX = "nasdaq_annual_reports/"

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "eda"

# nasdaq_annual_reports/apple-inc/NASDAQ_AAPL_2019.pdf
# Variant in 48 files: NASDAQ_ICUI_2016_<32-hex hash>.pdf
KEY_PATTERN = re.compile(
    r"^nasdaq_annual_reports/"
    r"(?P<company>[^/]+)/"
    r"(?P<exchange>[A-Za-z]+)_(?P<ticker>[^_/]+)_(?P<fiscal_year>\d{4})"
    r"(?:_(?P<suffix>[0-9a-f]{32}))?\.pdf$",
    re.IGNORECASE,
)


def get_client():
    """S3 client. Uses the keys in .env if they exist; otherwise tries anonymous access."""
    key = os.getenv("AWS_ACCESS_KEY_ID")
    secret = os.getenv("AWS_SECRET_ACCESS_KEY")
    region = os.getenv("AWS_REGION", "us-east-1")

    if key and secret:
        print("Connecting with the credentials in .env")
        return boto3.client(
            "s3",
            aws_access_key_id=key,
            aws_secret_access_key=secret,
            region_name=region,
        )

    print("No credentials in .env, trying anonymous access")
    return boto3.client("s3", config=Config(signature_version=UNSIGNED), region_name=region)


def list_all(client, limit=None):
    """Lists the objects under the prefix. limit=None returns all of them."""
    paginator = client.get_paginator("list_objects_v2")
    objects = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith("/"):
                continue
            objects.append({"key": obj["Key"], "size": obj["Size"]})
            if limit and len(objects) >= limit:
                return objects
    return objects


def parse(objects):
    """Separates the paths that follow the convention from the ones that don't."""
    rows, unparsed = [], []
    for o in objects:
        m = KEY_PATTERN.match(o["key"])
        if m:
            rows.append({
                "s3_key": o["key"],
                "company": m["company"],
                "exchange": m["exchange"].upper(),
                "ticker": m["ticker"].upper(),
                "fiscal_year": int(m["fiscal_year"]),
                "size_mb": round(o["size"] / 1024**2, 3),
                "has_hash_suffix": m["suffix"] is not None,
            })
        else:
            unparsed.append({"s3_key": o["key"], "size_mb": round(o["size"] / 1024**2, 3)})
    return rows, unparsed


def save(rows, unparsed):
    OUT.mkdir(parents=True, exist_ok=True)

    inv_path = OUT / "bucket_inventory.csv"
    with open(inv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["s3_key", "company", "exchange", "ticker", "fiscal_year", "size_mb", "has_hash_suffix"])
        w.writeheader()
        w.writerows(rows)

    unparsed_path = OUT / "bucket_unparsed.csv"
    with open(unparsed_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["s3_key", "size_mb"])
        w.writeheader()
        w.writerows(unparsed)

    print(f"\nSaved: {inv_path.relative_to(ROOT)}  ({len(rows):,} rows)")
    print(f"Saved: {unparsed_path.relative_to(ROOT)}  ({len(unparsed):,} rows)")


def analyze(objects, rows, unparsed):
    total = len(objects)
    total_size = sum(o["size"] for o in objects)

    print("\n" + "=" * 70)
    print(f"FILES: {total:,}")
    print(f"TOTAL SIZE: {total_size / 1024**3:.2f} GB")
    if total:
        print(f"AVERAGE SIZE: {total_size / total / 1024**2:.2f} MB per file")
    print("=" * 70)

    # --- Extensions ---
    ext = Counter(os.path.splitext(o["key"])[1].lower() or "(no extension)" for o in objects)
    print("\nEXTENSIONS")
    for e, n in ext.most_common(10):
        print(f"  {e:<20} {n:>8,}")

    # --- Folder depth ---
    depth = Counter(o["key"].count("/") for o in objects)
    print("\nFOLDER LEVELS (includes the base prefix)")
    for d, n in sorted(depth.items()):
        print(f"  {d} levels         {n:>8,}")

    # --- Naming convention ---
    print("\nNAMING CONVENTION")
    print(f"  Follow it       {len(rows):>8,}")
    print(f"  Don't follow it {len(unparsed):>8,}")
    for s in unparsed[:10]:
        print(f"    {s['s3_key']}")
    if len(unparsed) > 10:
        print(f"    ... and {len(unparsed) - 10:,} more (see bucket_unparsed.csv)")

    # --- Companies ---
    companies = {r["company"] for r in rows}
    print(f"\nDISTINCT COMPANIES: {len(companies):,}")

    # --- Years: one per file, taken from the name ---
    years = Counter(r["fiscal_year"] for r in rows)
    print("\nFISCAL YEAR PER FILE")
    for y, n in sorted(years.items()):
        print(f"  {y}   {n:>8,}")
    print(f"  sum   {sum(years.values()):>8,}")

    # --- Hash suffix ---
    with_hash = sum(r["has_hash_suffix"] for r in rows)
    print(f"\nWITH HASH SUFFIX: {with_hash:,}")

    # --- Duplicates: same ticker and year more than once ---
    pairs = Counter((r["ticker"], r["fiscal_year"]) for r in rows)
    dups = {k: n for k, n in pairs.items() if n > 1}
    print(f"\nDUPLICATES ticker+year: {len(dups):,}")
    for (t, y), n in list(dups.items())[:10]:
        print(f"  {t} {y}  x{n}")

    # --- Companies of interest ---
    targets = ["AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "META", "FB", "INTC", "GOOGL", "GOOG", "AMD", "NFLX"]
    by_ticker = defaultdict(list)
    for r in rows:
        by_ticker[r["ticker"]].append(r["fiscal_year"])
    print("\nCOMPANIES OF INTEREST")
    for t in targets:
        if t in by_ticker:
            print(f"  {t:<8} {sorted(by_ticker[t])}")
        else:
            print(f"  {t:<8} not in the bucket")


def main():
    client = get_client()
    print(f"Listing s3://{BUCKET}/{PREFIX} ...")
    try:
        objects = list_all(client)
    except Exception as e:
        print(f"\nERROR while listing: {type(e).__name__}: {e}")
        print("\nCheck that .env has AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY")
        return
    if not objects:
        print("No objects found. Check the bucket name and the prefix.")
        return

    rows, unparsed = parse(objects)
    analyze(objects, rows, unparsed)
    save(rows, unparsed)
    print("\nDone. Nothing was downloaded, only listed.")


if __name__ == "__main__":
    main()
