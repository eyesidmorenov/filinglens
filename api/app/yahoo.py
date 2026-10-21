"""Yahoo Finance snapshots: the fiscal years after the 10-Ks (agreed on 2026-10-20).

The yahoo-finance/ job saves one JSON per company in data/yahoo/snapshots/<TICKER>.json.
The API never calls Yahoo: it only reads those files, so the chat works even if Yahoo is down.

When a question asks about a year that is not in the index but is in the company's snapshot,
the snapshot becomes one more Contract 3 chunk for tenk-answer, like a 10-K chunk:
section "Yahoo Finance (fetched on <date>)" and page 0 (there is no page to cite).
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from pathlib import Path
from typing import Any

# In Docker, ./data/yahoo is mounted read-only at /app/data/yahoo (see docker-compose.yml)
YAHOO_DIR = Path(os.environ.get("YAHOO_DIR", Path(__file__).resolve().parents[2] / "data" / "yahoo"))

PAGE = 0  # a snapshot has no page: the chat shows "Yahoo Finance · fetched on <date>" instead

# The figures in the order they are written for Claude, as yahoo-finance/src/coverage.py names them
FIGURE_ORDER = (
    "Total Revenue",
    "Gross Profit",
    "Operating Income",
    "Net Income",
    "Total Assets",
    "Total Debt",
    "Stockholders Equity",
    "Operating Cash Flow",
    "Free Cash Flow",
)

# A ticker can come from the request body: only plain tickers name a file
TICKER_PATTERN = re.compile(r"[A-Z][A-Z0-9.\-]{0,11}")

logger = logging.getLogger(__name__)


def load_snapshot(ticker: str) -> dict[str, Any] | None:
    """The company's snapshot, or None when there is none (or it can't be read)."""
    if not ticker or not TICKER_PATTERN.fullmatch(ticker):
        return None
    path = YAHOO_DIR / "snapshots" / f"{ticker}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("Could not read the Yahoo snapshot %s", path)
        return None
    return data if isinstance(data, dict) else None


def _value(values: dict[str, Any], fiscal_year: int) -> float | None:
    """One figure for one year. JSON keys are strings ("2023")."""
    value = values.get(str(fiscal_year), values.get(fiscal_year))
    if isinstance(value, bool) or not isinstance(value, (int, float)) or math.isnan(value):
        return None
    return float(value)


def figures(snapshot: dict[str, Any], fiscal_year: int) -> dict[str, float]:
    """The figures the snapshot has for that fiscal year, in FIGURE_ORDER."""
    all_figures = snapshot.get("figures") or {}
    names = [n for n in FIGURE_ORDER if n in all_figures] + [n for n in all_figures if n not in FIGURE_ORDER]
    found = {}
    for name in names:
        values = all_figures.get(name)
        if isinstance(values, dict) and (value := _value(values, fiscal_year)) is not None:
            found[name] = value
    return found


def years(ticker: str) -> tuple[int, ...]:
    """The fiscal years with at least one figure in the company's snapshot, oldest first."""
    snapshot = load_snapshot(ticker)
    if not snapshot:
        return ()
    found: set[int] = set()
    for values in (snapshot.get("figures") or {}).values():
        if isinstance(values, dict):
            for key in values:
                if str(key).isdigit() and _value(values, int(key)) is not None:
                    found.add(int(key))
    return tuple(sorted(found))


def fetched_on(snapshot: dict[str, Any]) -> str:
    """The date the figures were fetched: "2026-10-20"."""
    return str(snapshot.get("fetched_at") or "")[:10] or "unknown date"


def _amount(value: float, currency: str) -> str:
    """416161000000, "USD" -> "416,161,000,000 USD (about 416.2 billion)"."""
    text = f"{value:,.0f} {currency}".strip()
    size = abs(value)
    if size >= 1e9:
        return f"{text} (about {value / 1e9:,.1f} billion)"
    if size >= 1e6:
        return f"{text} (about {value / 1e6:,.1f} million)"
    return text


def chunk(ticker: str, fiscal_year: int, company: str) -> dict[str, Any] | None:
    """The snapshot of one company and year as a Contract 3 chunk, or None if there are no figures."""
    snapshot = load_snapshot(ticker)
    if not snapshot:
        return None
    found = figures(snapshot, fiscal_year)
    if not found:
        return None

    currency = str(snapshot.get("currency") or "")
    date = fetched_on(snapshot)
    ended = (snapshot.get("fiscal_year_end") or {}).get(str(fiscal_year))
    ended_text = f", which ended about {ended}" if ended else ""
    lines = [
        f"Yahoo Finance annual figures for {company} ({ticker}), fiscal year {fiscal_year}{ended_text}.",
        f"Source: Yahoo Finance, fetched on {date}. These figures are not from the company's 10-K filing: "
        "Yahoo may name line items differently and may restate past years.",
        f"Amounts in {currency}:" if currency else "Amounts:",
    ]
    lines += [f"- {name}: {_amount(value, currency)}" for name, value in found.items()]

    return {
        "chunk_id": f"yahoo-{ticker}-{fiscal_year}",
        "text": "\n".join(lines),
        "score": 1.0,
        "section": f"Yahoo Finance (fetched on {date})",
        "page": PAGE,
        "company": company,
        "fiscal_year": fiscal_year,
    }
