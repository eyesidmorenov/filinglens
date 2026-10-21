"""The tests run without Elasticsearch: the catalog of companies comes from a fixture
with the first 25 companies, instead of the index."""

import csv
import sys
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app import catalog, company_year, yahoo  # noqa: E402

FIXTURE = Path(__file__).with_name("fixtures") / "companies_25.csv"


def fixture_catalog(path: Path = FIXTURE) -> catalog.Catalog:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return catalog.Catalog(
        names={(r["ticker"], int(r["fiscal_year"])): r["company_name"] for r in rows},
        folders={r["ticker"]: r["company"] for r in rows},
    )


@pytest.fixture(autouse=True)
def companies_from_fixture(monkeypatch):
    companies = fixture_catalog()
    monkeypatch.setattr(catalog, "load", lambda: companies)
    company_year._catalog.cache_clear()
    yield companies
    company_year._catalog.cache_clear()


@pytest.fixture(autouse=True)
def no_yahoo_snapshots(tmp_path, monkeypatch):
    """The snapshots in data/yahoo on your computer don't change the tests: start with none."""
    monkeypatch.setattr(yahoo, "YAHOO_DIR", tmp_path / "no-yahoo")
