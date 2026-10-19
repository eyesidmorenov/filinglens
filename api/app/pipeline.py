"""Answer pipeline: hybrid search (search/) + cited answer (tenk-answer).

question + ticker + fiscal_year
        -> search()   -> Contract 3 chunks  (José Luis's HybridRetriever)
        -> generate() -> Contract 4 answer  (Juan Carlos's AnswerGenerator)

Both heavy pieces (BGE model, Claude client) are created once. warm_up() loads
them in the background when the API starts, so /health answers right away and
the first question doesn't wait for the model.
"""

from __future__ import annotations

import csv
import logging
import os
import queue
import sys
import threading
import time
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from .company_year import analyze_company_year, clarification_message, extract_company_year

# search/ is a folder of the repo, not an installed package. In Docker it is
# copied to /app/search (see api/Dockerfile); locally it is <repo>/search.
SEARCH_DIR = Path(os.environ.get("SEARCH_DIR", Path(__file__).resolve().parents[2] / "search"))
if str(SEARCH_DIR) not in sys.path:
    sys.path.insert(0, str(SEARCH_DIR))

# Official company name per ticker and year, taken from the 10-K covers (Lourdes).
# The index stores "apple-inc"; citations should say "Apple Inc.".
COMPANY_NAMES_CSV = Path(__file__).resolve().parent / "company_names_25.csv"

logger = logging.getLogger(__name__)

MISSING_COMPANY_OR_YEAR = (
    "I couldn't identify the company and fiscal year in your question. "
    "Please mention one of our 25 NASDAQ companies and a year between 2019 and 2021."
)


@lru_cache(maxsize=1)
def company_names() -> dict[tuple[str, int], str]:
    with COMPANY_NAMES_CSV.open(encoding="utf-8") as f:
        return {(row["ticker"], int(row["fiscal_year"])): row["company_name"] for row in csv.DictReader(f)}


_retriever = None
_retriever_lock = threading.Lock()


def get_retriever():
    # A lock instead of lru_cache: warm_up() and the first question may ask for it
    # at the same time, and the BGE model must be loaded only once.
    global _retriever
    with _retriever_lock:
        if _retriever is None:
            from src.retrieval import HybridRetriever  # search/src/retrieval.py

            _retriever = HybridRetriever.from_settings()
    return _retriever


def warm_up() -> None:
    """Load the BGE model and run one search before the first question (backlog #3).

    Without it, the first question waited 17-39 s for the model to load.
    """
    log = logging.getLogger("uvicorn.error")  # so the message shows in `docker compose logs api`
    start = time.perf_counter()
    try:
        get_retriever().run("warm up", "AAPL", 2019)  # loads BGE and opens the Elasticsearch connection
        get_generator()
    except Exception:
        log.exception("Warm-up failed; the first question will load the model instead")
        return
    log.info("Warm-up done in %.1f s: the BGE model is ready", time.perf_counter() - start)


@lru_cache(maxsize=1)
def get_generator():
    from haystack.utils import Secret
    from tenk_answer import AnswerGenerator

    return AnswerGenerator(
        api_key=Secret.from_env_var("ANTHROPIC_API_KEY"),
        temperature=None,
        max_tokens=2048,
        # JSON enforced by the API: a forced tool call sometimes came back without
        # "status" or with the sources as XML inside "answer" (HTTP 500)
        structured_output=True,
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


def resolve_company_year(
    question: str, ticker: str | None = None, fiscal_year: int | None = None
) -> tuple[str | None, int | None, str | None]:
    """Find the company and year. Returns (ticker, fiscal_year, None), or (None, None, message) when we can't answer."""
    match = analyze_company_year(question)

    if ticker is None or fiscal_year is None:
        ticker = ticker or match.ticker
        fiscal_year = fiscal_year or match.fiscal_year

    if ticker:
        ticker = ticker.strip().upper()

    # Outside our 25 companies or 2019-2021: don't search, say we don't know.
    if (ticker, fiscal_year) not in company_names():
        message = clarification_message(match, ticker=ticker, fiscal_year=fiscal_year)
        return None, None, message or MISSING_COMPANY_OR_YEAR

    return ticker, fiscal_year, None


def answer_question(question: str, ticker: str | None = None, fiscal_year: int | None = None) -> dict:
    ticker, fiscal_year, message = resolve_company_year(question, ticker, fiscal_year)
    if message:
        return {"answer": message, "sources": [], "latency_ms": 0}

    hits = search(question, ticker, fiscal_year)
    return generate(question, hits)


# Shown to the user when search or Claude fails, in /ask and /ask/stream
ANSWER_ERROR = "Something went wrong while writing the answer. Please try again in a moment."
_END = object()


def answer_question_stream(
    question: str, ticker: str | None = None, fiscal_year: int | None = None
) -> Iterator[dict]:
    """Like answer_question, but yields the answer while Claude writes it.

    Events, in order:
      {"type": "token", "text": "..."}   one per new piece of text (a preview)
      {"type": "final", "answer", "sources", "latency_ms"}   the answer to keep (Contract 4)
    or, if something fails: {"type": "error", "message": "..."}
    """
    try:
        ticker, fiscal_year, message = resolve_company_year(question, ticker, fiscal_year)
        if message:
            yield {"type": "final", "answer": message, "sources": [], "latency_ms": 0}
            return
        hits = search(question, ticker, fiscal_year)
    except Exception:
        logger.exception("Search failed")
        yield {"type": "error", "message": ANSWER_ERROR}
        return

    # tenk-answer's stream() waits until Claude finishes and calls on_token along the way.
    # It runs in its own thread and drops each piece in a queue, so we can send them right away.
    events: queue.Queue = queue.Queue()

    def write_answer() -> None:
        try:
            answer = get_generator().stream(
                question=question,
                documents=hits,
                on_token=lambda text: events.put({"type": "token", "text": text}),
            )
            events.put({"type": "final", **answer.to_api_response()})
        except Exception:
            logger.exception("Answer generation failed")
            events.put({"type": "error", "message": ANSWER_ERROR})
        finally:
            events.put(_END)

    threading.Thread(target=write_answer, daemon=True).start()
    while (event := events.get()) is not _END:
        yield event
