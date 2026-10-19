"""The companies and fiscal years the chatbot can answer for, read from the index.

The index is the single source of truth: the ETL stores each filing's official
name (company_name, from its 10-K cover) in every chunk. Adding companies is
running the ETL, loading the index and restarting the API, with no code change.

The catalog is read once, on the first question or at warm-up, with one
aggregation over the index. A failed read is not cached: the next question
tries again.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

ES_URL = os.environ.get("ELASTICSEARCH_URL", "http://localhost:9200")
ES_INDEX = os.environ.get("ES_INDEX", "filinglens-chunks")
MAX_COMPANIES = 10_000


@dataclass(frozen=True)
class Catalog:
    # (ticker, fiscal_year) -> official name on that year's 10-K cover ("Meta Platforms, Inc.")
    names: dict[tuple[str, int], str]
    # ticker -> S3 folder name ("meta-platforms-inc")
    folders: dict[str, str]

    @property
    def tickers(self) -> frozenset[str]:
        return frozenset(ticker for ticker, _ in self.names)

    @property
    def years(self) -> tuple[int, ...]:
        return tuple(sorted({year for _, year in self.names}))


def name_from_folder(folder: str) -> str:
    """For an index loaded before company_name existed: "apple-inc" -> "Apple Inc"."""
    return " ".join(part.capitalize() for part in folder.split("-"))


def from_aggregation(buckets: list[dict]) -> Catalog:
    """Build the catalog from the index's ticker > fiscal_year > company_name buckets."""
    names: dict[tuple[str, int], str] = {}
    folders: dict[str, str] = {}
    for ticker_bucket in buckets:
        ticker = ticker_bucket["key"]
        folder_buckets = ticker_bucket["folder"]["buckets"]
        if folder_buckets:
            folders[ticker] = folder_buckets[0]["key"]
        for year_bucket in ticker_bucket["years"]["buckets"]:
            name_buckets = year_bucket["name"]["buckets"]
            name = name_buckets[0]["key"] if name_buckets else name_from_folder(folders.get(ticker, ticker))
            names[(ticker, int(year_bucket["key"]))] = name
    return Catalog(names=names, folders=folders)


def query_index() -> list[dict]:
    from elasticsearch import Elasticsearch

    response = Elasticsearch(ES_URL).search(
        index=ES_INDEX,
        size=0,
        aggs={
            "tickers": {
                "terms": {"field": "ticker", "size": MAX_COMPANIES},
                "aggs": {
                    "folder": {"terms": {"field": "company", "size": 1}},
                    "years": {
                        "terms": {"field": "fiscal_year", "size": 100},
                        "aggs": {"name": {"terms": {"field": "company_name", "size": 1}}},
                    },
                },
            }
        },
    )
    return response["aggregations"]["tickers"]["buckets"]


@lru_cache(maxsize=1)
def load() -> Catalog:
    """The companies and years in the index. Cached for the life of the API."""
    catalog = from_aggregation(query_index())
    if not catalog.names:
        raise RuntimeError(f"Index {ES_INDEX!r} at {ES_URL} has no companies: load the index first")
    return catalog
