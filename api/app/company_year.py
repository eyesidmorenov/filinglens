"""Extract a supported FilingLens company and fiscal year from a question.

This module is deliberately deterministic and offline. It does not call an LLM,
Elasticsearch, the retriever, or the answer generator. The public tuple-returning
function matches the placeholder introduced by API integration PR #15.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

SUPPORTED_YEARS = frozenset({2019, 2020, 2021})
COMPANY_NAMES_CSV = Path(__file__).with_name("company_names_25.csv")

# User-facing names that cannot be derived reliably from the official CSV alone.
# All aliases are normalized before matching, so accents and apostrophe styles do
# not need separate entries.
EXTRA_ALIASES: dict[str, tuple[str, ...]] = {
    "AAPL": ("Apple",),
    "ADBE": ("Adobe", "Adobe Systems"),
    "ADSK": ("Autodesk",),
    "AMGN": ("Amgen",),
    "ATVI": ("Activision", "Activision Blizzard"),
    "CMCSA": ("Comcast",),
    "CTSH": ("Cognizant", "Cognizant Technology Solutions"),
    "DXCM": ("DexCom",),
    "EA": ("Electronic Arts",),
    "EBAY": ("eBay",),
    "FB": ("Facebook", "Facebook Inc", "Meta", "Meta Platforms"),
    "GILD": ("Gilead", "Gilead Sciences"),
    "IDXX": ("IDEXX", "IDEXX Laboratories"),
    "ILMN": ("Illumina",),
    "KLAC": ("KLA", "KLA Corporation", "KLA Tencor"),
    "LRCX": ("Lam Research",),
    "MAR": ("Marriott", "Marriott International"),
    "MDLZ": ("Mondelez", "Mondelez International"),
    "NVDA": ("NVIDIA",),
    "ORLY": ("O'Reilly", "O’Reilly", "O Reilly", "O'Reilly Automotive"),
    "PAYX": ("Paychex",),
    "QCOM": ("Qualcomm",),
    "SBUX": ("Starbucks",),
    "TXN": ("Texas Instruments",),
    "VRTX": ("Vertex", "Vertex Pharmaceuticals"),
}

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


@lru_cache(maxsize=1)
def _catalog() -> tuple[frozenset[str], dict[str, frozenset[str]]]:
    """Read supported tickers and combine official names with explicit aliases."""

    aliases: dict[str, set[str]] = {}
    with COMPANY_NAMES_CSV.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    required = {"ticker", "company", "company_name"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"{COMPANY_NAMES_CSV} does not have the expected columns: {sorted(required)}")

    for row in rows:
        ticker = row["ticker"].strip().upper()
        aliases.setdefault(ticker, set())
        for value in (row["company"].replace("-", " "), row["company_name"]):
            normalized = _normalize_words(value)
            if normalized:
                aliases[ticker].add(normalized)

    for ticker, values in EXTRA_ALIASES.items():
        if ticker not in aliases:
            raise ValueError(f"alias configured for unsupported ticker {ticker}")
        aliases[ticker].update(_normalize_words(value) for value in values)

    frozen_aliases = {ticker: frozenset(values) for ticker, values in aliases.items()}
    return frozenset(aliases), frozen_aliases


def supported_tickers() -> frozenset[str]:
    """The 25 tickers supported by the current FilingLens dataset."""

    return _catalog()[0]


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
            problems.append("Please mention one of the 25 supported NASDAQ companies.")

    if effective_year is None:
        if match.year_is_ambiguous:
            problems.append("I found more than one year; please ask about one fiscal year at a time.")
        else:
            problems.append("Please specify a fiscal year: 2019, 2020, or 2021.")
    elif effective_year not in SUPPORTED_YEARS:
        problems.append("That fiscal year is outside the supported range; please use 2019, 2020, or 2021.")

    return " ".join(problems)
