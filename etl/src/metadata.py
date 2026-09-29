"""
Document metadata comes from the file path, never from the PDF content.

The inventory written by eda/download_sample.py is the primary source. When a
PDF is not listed there, the same fields are rebuilt from its local name
(<TICKER>_<YEAR>.pdf) or from its S3 key (<company>/NASDAQ_<TICKER>_<YEAR>.pdf).
"""

import csv
import re
from pathlib import Path

LOCAL_NAME = re.compile(r"^(?P<ticker>[A-Z0-9.\-]+)_(?P<year>\d{4})\.pdf$", re.IGNORECASE)
S3_NAME = re.compile(
    r"(?P<company>[^/]+)/(?P<exchange>[A-Z]+)_(?P<ticker>[A-Z0-9.\-]+)_(?P<year>\d{4})\.pdf$",
    re.IGNORECASE,
)


def make_doc_id(ticker: str, year: int) -> str:
    # The team contract keeps the _10K suffix for every document; the real
    # document kind travels in doc_type.
    return f"{ticker.upper()}_{year}_10K"


def parse_local_name(filename: str) -> dict | None:
    """AAPL_2019.pdf -> {'ticker': 'AAPL', 'fiscal_year': 2019}"""
    m = LOCAL_NAME.match(Path(filename).name)
    if not m:
        return None
    return {"ticker": m["ticker"].upper(), "fiscal_year": int(m["year"])}


def parse_s3_key(key: str) -> dict | None:
    """nasdaq_annual_reports/apple-inc/NASDAQ_AAPL_2019.pdf -> company, exchange, ticker, year"""
    m = S3_NAME.search(key)
    if not m:
        return None
    return {
        "company": m["company"],
        "exchange": m["exchange"].upper(),
        "ticker": m["ticker"].upper(),
        "fiscal_year": int(m["year"]),
    }


def load_inventory(path: Path) -> dict[str, dict]:
    """Read inventario.csv, keyed by local file name (AAPL_2019.pdf)."""
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = {}
    for r in rows:
        r["fiscal_year"] = int(r["fiscal_year"])
        r["size_mb"] = float(r["size_mb"])
        out[Path(r["local_path"]).name] = r
    return out


def metadata_for(pdf: Path, inventory: dict[str, dict]) -> dict:
    """All contract metadata fields for one PDF except n_pages."""
    if pdf.name in inventory:
        row = dict(inventory[pdf.name])
        row["doc_id"] = make_doc_id(row["ticker"], row["fiscal_year"])
        return row

    parsed = parse_local_name(pdf.name)
    if parsed is None:
        raise ValueError(f"Cannot read ticker and year from file name: {pdf.name}")
    return {
        "doc_id": make_doc_id(parsed["ticker"], parsed["fiscal_year"]),
        "company": "unknown",
        "ticker": parsed["ticker"],
        "fiscal_year": parsed["fiscal_year"],
        "exchange": "NASDAQ",
        "s3_key": "",
        "local_path": f"data/raw/{pdf.name}",
        "size_mb": round(pdf.stat().st_size / 1024**2, 2),
    }
