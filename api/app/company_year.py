"""Extract a supported FilingLens company and fiscal year from a question.

This module is deterministic: it does not call an LLM, the retriever, or the
answer generator. The companies and years it knows come from the index
(catalog.py), read once; matching a question is then offline. The public
tuple-returning function matches the placeholder introduced by API integration PR #15.

Names a company answers to, all normalized (case, accents, punctuation):
  - its official names on its 10-K covers ("Meta Platforms, Inc.", "Facebook, Inc.")
    and the same names without the legal ending ("Meta Platforms", "Facebook");
  - its S3 folder name ("meta-platforms-inc");
  - nicknames that can't be derived from the official name, in company_aliases.csv
    (data, not code: "Meta", "Gilead", "IDEXX").
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import catalog

NICKNAMES_CSV = Path(__file__).with_name("company_aliases.csv")

# Endings dropped from an official name to get the name people use, repeatedly:
# "United Airlines Holdings, Inc." -> "United Airlines", "Marriott International, Inc." -> "Marriott"
LEGAL_ENDINGS = (
    "public limited company", "incorporated", "corporation", "holdings", "international",
    "company", "limited", "group", "corp", "inc", "ltd", "plc", "llc", "s a", "n v", "co", "lp", "sa", "nv", "ag", "se",
)
# Short names that are also the name of the stock exchange: "a NASDAQ company" is not Nasdaq, Inc.,
# but "What did Nasdaq report in 2021?" is. They count as the company unless the words around
# them point to the exchange. The full name ("Nasdaq, Inc.") and the ticker (NDAQ) always work.
TOO_GENERIC = frozenset({"nasdaq"})
EXCHANGE_WORDS_AFTER = frozenset({
    "companies", "company", "firms", "firm", "issuers", "listed", "listing", "listings", "stock", "stocks",
    "market", "markets", "exchange", "composite", "index", "100", "global", "rules",
})
EXCHANGE_WORDS_BEFORE = frozenset({"a", "an", "on", "other", "traded", "listed"})

# Capture any plausible four-digit year. A unique unsupported year is returned
# unchanged; pipeline.py owns the 2019-2021 scope check and must reject it before
# search or Claude are called.
YEAR_PATTERN = re.compile(r"(?<!\d)(?:19|20|21)\d{2}(?!\d)")


@dataclass(frozen=True)
class CompanyYearMatch:
    """Detailed parse result used to explain missing or ambiguous information."""

    ticker: str | None
    fiscal_year: int | None
    company_candidates: tuple[str, ...]
    year_candidates: tuple[int, ...]

    @property
    def company_is_ambiguous(self) -> bool:
        return len(self.company_candidates) > 1

    @property
    def year_is_ambiguous(self) -> bool:
        return len(self.year_candidates) > 1


def _normalize_words(value: str) -> str:
    """Case-fold text, remove accents, and turn punctuation into word spaces."""

    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", without_marks.casefold()).split())


def short_name(normalized_name: str) -> str:
    """Drop the legal endings and a leading "the": "the kraft heinz company" -> "kraft heinz"."""

    words = normalized_name.removeprefix("the ")
    changed = True
    while changed:
        changed = False
        for ending in LEGAL_ENDINGS:
            if words.endswith(" " + ending):
                words = words[: -len(ending) - 1]
                changed = True
    return words


def _nicknames() -> dict[str, set[str]]:
    with NICKNAMES_CSV.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    nicknames: dict[str, set[str]] = {}
    for row in rows:
        nicknames.setdefault(row["ticker"].strip().upper(), set()).add(_normalize_words(row["alias"]))
    return nicknames


def _generic_names() -> dict[str, frozenset[str]]:
    """Short names in TOO_GENERIC, per ticker: they need the context check in _names_the_company.

    Not cached: catalog.load() already is, and this is one pass over ~150 names.
    """

    generic: dict[str, set[str]] = {}
    for (ticker, _), official in catalog.load().names.items():
        if (short := short_name(_normalize_words(official))) in TOO_GENERIC:
            generic.setdefault(ticker, set()).add(short)
    return {ticker: frozenset(names) for ticker, names in generic.items()}


def _names_the_company(normalized_question: str, name: str) -> bool:
    """True when some mention of `name` is the company, not the exchange.

    "drove nasdaq s net revenues" -> True; "which nasdaq company", "listed on the nasdaq" -> False.
    """
    words = normalized_question.split()
    size = len(name.split())
    for i in range(len(words) - size + 1):
        if " ".join(words[i : i + size]) != name:
            continue
        after = words[i + size] if i + size < len(words) else ""
        before = words[i - 1] if i > 0 else ""
        two_before = words[i - 2] if i > 1 else ""
        if after in EXCHANGE_WORDS_AFTER or before in EXCHANGE_WORDS_BEFORE:
            continue
        if before == "the" and two_before in EXCHANGE_WORDS_BEFORE:
            continue
        return True
    return False


@lru_cache(maxsize=1)
def _catalog() -> tuple[frozenset[str], dict[str, frozenset[str]]]:
    """Supported tickers (from the index) and the names each one answers to."""

    companies = catalog.load()
    aliases: dict[str, set[str]] = {ticker: set() for ticker in companies.tickers}
    for (ticker, _), official in companies.names.items():
        full = _normalize_words(official)
        aliases[ticker].add(full)
        if (short := short_name(full)) and short not in TOO_GENERIC:
            aliases[ticker].add(short)
    for ticker, folder in companies.folders.items():
        aliases[ticker].add(_normalize_words(folder))

    # Nicknames of companies that are not in the index are simply not used
    for ticker, values in _nicknames().items():
        if ticker in aliases:
            aliases[ticker].update(values)

    frozen_aliases = {ticker: frozenset(v for v in values if v) for ticker, values in aliases.items()}
    return frozenset(aliases), frozen_aliases


def supported_tickers() -> frozenset[str]:
    """The tickers in the index."""

    return _catalog()[0]


def supported_years() -> tuple[int, ...]:
    """The fiscal years in the index, oldest first."""

    return catalog.load().years


def _years_text() -> str:
    """2019, 2020, or 2021"""

    years = [str(y) for y in supported_years()]
    if len(years) <= 2:
        return " or ".join(years)
    return ", ".join(years[:-1]) + ", or " + years[-1]


def _has_phrase(normalized_question: str, normalized_alias: str) -> bool:
    return f" {normalized_alias} " in f" {normalized_question} "


def _company_candidates(question: str) -> tuple[str, ...]:
    tickers, aliases = _catalog()
    found: set[str] = set()

    # Tickers are accepted only in uppercase, including explicit $TICKER syntax.
    # This prevents short tickers such as EA and MAR from matching normal words.
    for token in re.findall(r"(?<![A-Za-z0-9])\$([A-Za-z][A-Za-z0-9.\-]{0,11})(?![A-Za-z0-9])", question):
        if token in tickers:
            found.add(token)

    # Bare ticker notation is case-sensitive. This avoids treating ordinary
    # lower-case words as short tickers such as EA or MAR.
    for ticker in tickers:
        pattern = rf"(?<![A-Za-z0-9]){re.escape(ticker)}(?![A-Za-z0-9])"
        if re.search(pattern, question):
            found.add(ticker)

    normalized_question = _normalize_words(question)
    for ticker, names in aliases.items():
        if any(_has_phrase(normalized_question, name) for name in names):
            found.add(ticker)
    for ticker, names in _generic_names().items():
        if any(_names_the_company(normalized_question, name) for name in names):
            found.add(ticker)

    return tuple(sorted(found))


def _year_candidates(question: str) -> tuple[int, ...]:
    return tuple(sorted({int(value) for value in YEAR_PATTERN.findall(question)}))


def analyze_company_year(question: str) -> CompanyYearMatch:
    """Return candidates plus a value only when that dimension is unambiguous."""

    if not isinstance(question, str):
        raise TypeError("question must be a string")

    companies = _company_candidates(question)
    years = _year_candidates(question)
    ticker = companies[0] if len(companies) == 1 else None
    fiscal_year = years[0] if len(years) == 1 else None
    return CompanyYearMatch(
        ticker=ticker,
        fiscal_year=fiscal_year,
        company_candidates=companies,
        year_candidates=years,
    )


def extract_company_year(question: str) -> tuple[str | None, int | None]:
    """Compatibility function for api/app/pipeline.py from PR #15."""

    match = analyze_company_year(question)
    return match.ticker, match.fiscal_year


def clarification_message(
    match: CompanyYearMatch,
    *,
    ticker: str | None = None,
    fiscal_year: int | None = None,
) -> str:
    """Explain exactly which input is missing, ambiguous, or outside the scope."""

    effective_ticker = ticker.strip().upper() if ticker else match.ticker
    effective_year = int(fiscal_year) if fiscal_year is not None else match.fiscal_year
    problems: list[str] = []

    if effective_ticker is None or effective_ticker not in supported_tickers():
        if effective_ticker is None and match.company_is_ambiguous:
            problems.append("I found more than one company; please ask about one company at a time.")
        else:
            problems.append(f"Please mention one of the {len(supported_tickers())} supported NASDAQ companies.")

    if effective_year is None:
        if match.year_is_ambiguous:
            problems.append("I found more than one year; please ask about one fiscal year at a time.")
        else:
            problems.append(f"Please specify a fiscal year: {_years_text()}.")
    elif effective_year not in supported_years():
        problems.append(f"That fiscal year is outside the supported range; please use {_years_text()}.")

    return " ".join(problems)
