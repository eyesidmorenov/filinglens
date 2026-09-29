"""Context builder: assigns local ids D1..Dn in rank order and renders chunks within a token budget."""

from __future__ import annotations

import html
import logging
import math
import re
from collections.abc import Callable
from dataclasses import dataclass

from tenk_answer.types import SearchResult

logger = logging.getLogger(__name__)

TokenEstimator = Callable[[str], int]

# Matches opening or closing <document ...> tags (any case/spacing) inside chunk text.
_DOCUMENT_TAG = re.compile(r"<(\s*/?\s*document\b)", re.IGNORECASE)


def estimate_tokens(text: str) -> int:
    """Default estimator: ~4 characters per token."""
    return math.ceil(len(text) / 4)


@dataclass(frozen=True)
class ContextDocument:
    doc_id: str
    result: SearchResult
    rendered: str


@dataclass(frozen=True)
class BuiltContext:
    documents: list[ContextDocument]

    @property
    def text(self) -> str:
        return "\n".join(d.rendered for d in self.documents)

    def by_id(self) -> dict[str, SearchResult]:
        return {d.doc_id: d.result for d in self.documents}


def escape_content(text: str) -> str:
    """Neutralize <document> / </document> tags so chunk text cannot break out of its tag."""
    return _DOCUMENT_TAG.sub(r"&lt;\1", text)


def render_document(doc_id: str, result: SearchResult) -> str:
    def attr(value: object) -> str:
        return html.escape(str(value), quote=True)

    return (
        f'<document id="{doc_id}" company="{attr(result.company)}" fiscal_year="{result.fiscal_year}" '
        f'section="{attr(result.section)}" page="{result.page}">\n'
        f"{escape_content(result.text)}\n"
        f"</document>"
    )


def build_context(
    results: list[SearchResult],
    max_context_tokens: int,
    estimator: TokenEstimator = estimate_tokens,
) -> BuiltContext:
    """Take results in rank order until the next one would exceed `max_context_tokens`."""
    documents: list[ContextDocument] = []
    used = 0
    for result in results:
        doc_id = f"D{len(documents) + 1}"
        rendered = render_document(doc_id, result)
        cost = estimator(rendered)
        if used + cost > max_context_tokens:
            logger.info(
                "Context budget reached: kept %d of %d documents (%d/%d tokens)",
                len(documents),
                len(results),
                used,
                max_context_tokens,
            )
            break
        documents.append(ContextDocument(doc_id=doc_id, result=result, rendered=rendered))
        used += cost
    return BuiltContext(documents=documents)
