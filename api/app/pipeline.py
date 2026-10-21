"""Answer pipeline: hybrid search (search/) + cited answer (tenk-answer).

question + ticker + fiscal_year
        -> retrieve() -> Contract 3 chunks:
             a year in the index    -> search(), José Luis's HybridRetriever over the 10-Ks
             a later year (2022+)   -> the Yahoo Finance snapshot as one chunk (yahoo.py)
        -> generate() -> Contract 4 answer  (Juan Carlos's AnswerGenerator)

Both heavy pieces (BGE model, Claude client) are created once. warm_up() loads
them in the background when the API starts, so /health answers right away and
the first question doesn't wait for the model.
"""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import time
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from . import catalog, yahoo
from .company_year import analyze_company_year, clarification_message, supported_tickers

# search/ is a folder of the repo, not an installed package. In Docker it is
# copied to /app/search (see api/Dockerfile); locally it is <repo>/search.
SEARCH_DIR = Path(os.environ.get("SEARCH_DIR", Path(__file__).resolve().parents[2] / "search"))
if str(SEARCH_DIR) not in sys.path:
    sys.path.insert(0, str(SEARCH_DIR))

logger = logging.getLogger(__name__)

MISSING_COMPANY_OR_YEAR = (
    "I couldn't identify the company and fiscal year in your question. "
    "Please mention one of our NASDAQ companies and a fiscal year."
)


def company_names() -> dict[tuple[str, int], str]:
    """Official name per ticker and year, from the 10-K covers, read from the index (catalog.py).

    The chunks store the S3 folder ("apple-inc"); citations should say "Apple Inc.".
    """
    return catalog.load().names


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
        ticker, year = next(iter(company_names()))  # reads the catalog of companies from the index
        get_retriever().run("warm up", ticker, year)  # loads BGE and opens the Elasticsearch connection
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

    # A company and year in the index: the 10-Ks answer
    if (ticker, fiscal_year) in company_names():
        return ticker, fiscal_year, None

    # One of our companies, a year after the 10-Ks: Yahoo Finance answers if its snapshot has that year
    if ticker in supported_tickers() and fiscal_year is not None:
        if fiscal_year in yahoo.years(ticker):
            return ticker, fiscal_year, None
        return None, None, missing_year_message(ticker, fiscal_year)

    # A company or year we can't identify: don't search, say what is missing
    message = clarification_message(match, ticker=ticker, fiscal_year=fiscal_year)
    return None, None, message or MISSING_COMPANY_OR_YEAR


def company_name(ticker: str) -> str:
    """The latest official name of a company: FB -> "Meta Platforms, Inc."."""
    names = {year: name for (t, year), name in company_names().items() if t == ticker}
    return names[max(names)] if names else ticker


def _years_text(years: list[int]) -> str:
    """[2019, 2020, 2021] -> "2019 to 2021"; [2019, 2021] -> "2019 and 2021"."""
    if len(years) > 2 and years == list(range(years[0], years[-1] + 1)):
        return f"{years[0]} to {years[-1]}"
    words = [str(y) for y in years]
    return " and ".join(words) if len(words) <= 2 else ", ".join(words[:-1]) + " and " + words[-1]


def missing_year_message(ticker: str, fiscal_year: int) -> str:
    """One of our companies, a year we have no data for: say which years we do have."""
    filings = sorted(year for (t, year) in company_names() if t == ticker)
    name = company_name(ticker)
    message = f"I don't have fiscal {fiscal_year} for {name}" + ("" if name.endswith(".") else ".")
    if filings:
        message += f" I can answer about fiscal {_years_text(filings)} from its 10-K filings"
        later = [y for y in yahoo.years(ticker) if y not in filings]
        message += f", and fiscal {_years_text(later)} from Yahoo Finance." if later else "."
    return message


def retrieve(question: str, ticker: str, fiscal_year: int) -> list[dict]:
    """The chunks for tenk-answer: 10-K search for a year in the index, else the Yahoo snapshot."""
    if (ticker, fiscal_year) in company_names():
        return search(question, ticker, fiscal_year)
    snapshot_chunk = yahoo.chunk(ticker, fiscal_year, company_name(ticker))
    return [snapshot_chunk] if snapshot_chunk else []


def answer_question(question: str, ticker: str | None = None, fiscal_year: int | None = None) -> dict:
    ticker, fiscal_year, message = resolve_company_year(question, ticker, fiscal_year)
    if message:
        return {"answer": message, "sources": [], "latency_ms": 0}

    hits = retrieve(question, ticker, fiscal_year)
    return generate(question, hits)


# Shown to the user when search or Claude fails, in /ask and /ask/stream
ANSWER_ERROR = "Something went wrong while writing the answer. Please try again in a moment."
_END = object()


class StreamCancelled(Exception):
    """The user left (closed the page or pressed stop): Claude must stop writing."""


def answer_question_stream(
    question: str,
    ticker: str | None = None,
    fiscal_year: int | None = None,
    cancelled: threading.Event | None = None,
) -> Iterator[dict]:
    """Like answer_question, but yields the answer while Claude writes it.

    Events, in order:
      {"type": "token", "text": "..."}   one per new piece of text (a preview)
      {"type": "final", "answer", "sources", "latency_ms"}   the answer to keep (Contract 4)
    or, if something fails: {"type": "error", "message": "..."}

    Set `cancelled` to stop Claude at its next piece of text, so it stops spending tokens (backlog #7).
    """
    cancelled = cancelled or threading.Event()
    try:
        ticker, fiscal_year, message = resolve_company_year(question, ticker, fiscal_year)
        if message:
            yield {"type": "final", "answer": message, "sources": [], "latency_ms": 0}
            return
        hits = retrieve(question, ticker, fiscal_year)
    except Exception:
        logger.exception("Search failed")
        yield {"type": "error", "message": ANSWER_ERROR}
        return

    # tenk-answer's stream() waits until Claude finishes and calls on_token along the way.
    # It runs in its own thread and drops each piece in a queue, so we can send them right away.
    events: queue.Queue = queue.Queue()

    def on_token(text: str) -> None:
        if cancelled.is_set():
            raise StreamCancelled  # stops Claude's stream: no more tokens are spent
        events.put({"type": "token", "text": text})

    def write_answer() -> None:
        try:
            answer = get_generator().stream(question=question, documents=hits, on_token=on_token)
            events.put({"type": "final", **answer.to_api_response()})
        except StreamCancelled:
            logging.getLogger("uvicorn.error").info("Streaming cancelled: the user left, Claude stopped")
        except Exception:
            logger.exception("Answer generation failed")
            events.put({"type": "error", "message": ANSWER_ERROR})
        finally:
            events.put(_END)

    threading.Thread(target=write_answer, daemon=True).start()
    while (event := events.get()) is not _END:
        yield event
