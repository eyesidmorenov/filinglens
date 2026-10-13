"""Answer pipeline: hybrid search (search/) + cited answer (tenk-answer).

question + ticker + fiscal_year
        -> search()   -> Contract 3 chunks  (José Luis's HybridRetriever)
        -> generate() -> Contract 4 answer  (Juan Carlos's AnswerGenerator)

Both heavy pieces (BGE model, Claude client) are created once, on the first
question, so the API starts fast and /health answers right away.
"""

from __future__ import annotations

import csv
import os
import sys
from functools import lru_cache
from pathlib import Path

# search/ is a folder of the repo, not an installed package. In Docker it is
# copied to /app/search (see api/Dockerfile); locally it is <repo>/search.
SEARCH_DIR = Path(os.environ.get("SEARCH_DIR", Path(__file__).resolve().parents[2] / "search"))
if str(SEARCH_DIR) not in sys.path:
    sys.path.insert(0, str(SEARCH_DIR))

# Official company name per ticker and year, taken from the 10-K covers (Lourdes).
# The index stores "apple-inc"; citations should say "Apple Inc.".
COMPANY_NAMES_CSV = Path(__file__).resolve().parent / "company_names_25.csv"

MISSING_COMPANY_OR_YEAR = (
    "I couldn't identify the company and fiscal year in your question. "
    "Please mention one of our 25 NASDAQ companies and a year between 2019 and 2021."
)


@lru_cache(maxsize=1)
def company_names() -> dict[tuple[str, int], str]:
    with COMPANY_NAMES_CSV.open(encoding="utf-8") as f:
        return {(row["ticker"], int(row["fiscal_year"])): row["company_name"] for row in csv.DictReader(f)}


@lru_cache(maxsize=1)
def get_retriever():
    from src.retrieval import HybridRetriever  # search/src/retrieval.py

    return HybridRetriever.from_settings()


@lru_cache(maxsize=1)
def get_generator():
    from haystack.utils import Secret
    from tenk_answer import AnswerGenerator

    return AnswerGenerator(
        api_key=Secret.from_env_var("ANTHROPIC_API_KEY"),
        temperature=None,
        max_tokens=2048,
    )


def search(question: str, ticker: str, fiscal_year: int) -> list[dict]:
    """Return the best chunks for one company and year, in Contract 3."""
    from src.retrieval import to_contract3

    result = get_retriever().run(question, ticker, fiscal_year)
    hits = [to_contract3(doc) for doc in result.hybrid]

    # "apple-inc" -> "Apple Inc.", so Claude and the citations use the official name
    name = company_names().get((ticker, fiscal_year))
    if name:
        for hit in hits:
            hit["company"] = name
    return hits


def generate(question: str, hits: list[dict]) -> dict:
    """Turn the chunks into a cited answer, in Contract 4."""
    return get_generator().run(question=question, documents=hits).to_api_response()


def extract_company_year(question: str) -> tuple[str | None, int | None]:
    # TODO: replace with José Luis's piece (question -> ticker, fiscal_year)
    return None, None


def answer_question(question: str, ticker: str | None = None, fiscal_year: int | None = None) -> dict:
    if ticker is None or fiscal_year is None:
        found_ticker, found_year = extract_company_year(question)
        ticker = ticker or found_ticker
        fiscal_year = fiscal_year or found_year

    if ticker:
        ticker = ticker.strip().upper()

    # Outside our 25 companies or 2019-2021: don't search, say we don't know.
    if (ticker, fiscal_year) not in company_names():
        return {"answer": MISSING_COMPANY_OR_YEAR, "sources": [], "latency_ms": 0}

    hits = search(question, ticker, fiscal_year)
    return generate(question, hits)