"""Turns the model's `submit_answer` tool call into statuses and `Source`s, enforcing no-source-no-answer."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from haystack.dataclasses import ChatMessage
from pydantic import BaseModel, ValidationError

from tenk_answer.context import BuiltContext
from tenk_answer.errors import MalformedResponseError
from tenk_answer.prompts import SUBMIT_ANSWER_TOOL_NAME
from tenk_answer.types import AnswerStatus, SearchResult, Source

logger = logging.getLogger(__name__)

EXCERPT_FALLBACK_CHARS = 200

INSUFFICIENT_CONTEXT_MESSAGE = (
    "I don't know. The retrieved 10-K sections don't contain enough information to answer that question. "
    "Try rephrasing it, or ask about a specific company's risks, business or figures stated in its 10-K."
)
OUT_OF_SCOPE_MESSAGE = (
    "Sorry, I can't help with that. I can answer questions about a single company's 10-K, such as its risk "
    "factors, business model, competition, or figures stated in the filing. I can't compare companies, "
    "calculate growth or give investment advice."
)


class _ToolSource(BaseModel):
    doc_id: str
    excerpt: str


class _ToolOutput(BaseModel):
    status: AnswerStatus
    answer: str
    sources: list[_ToolSource]


@dataclass(frozen=True)
class ParsedAnswer:
    status: AnswerStatus
    answer: str
    sources: list[Source]


def _tool_arguments(reply: ChatMessage) -> dict[str, Any]:
    calls = [c for c in reply.tool_calls if c.tool_name == SUBMIT_ANSWER_TOOL_NAME]
    if not calls:
        finish = reply.meta.get("finish_reason")
        raise MalformedResponseError(
            f"Model did not call {SUBMIT_ANSWER_TOOL_NAME!r} (finish_reason={finish!r}, "
            f"tool_calls={[c.tool_name for c in reply.tool_calls]}, text={(reply.text or '')[:200]!r})"
        )
    arguments: Any = calls[0].arguments
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as e:
            raise MalformedResponseError(f"Tool arguments are not valid JSON: {e}") from e
    if not isinstance(arguments, dict):
        raise MalformedResponseError(f"Tool arguments must be an object, got {type(arguments).__name__}")
    return arguments


def _excerpt(excerpt: str, text: str) -> str:
    candidate = excerpt.strip()
    if candidate and candidate in text:
        return candidate
    logger.info("Excerpt not found verbatim in chunk; falling back to chunk prefix")
    return text[:EXCERPT_FALLBACK_CHARS].strip()


def _to_source(result: SearchResult, excerpt: str) -> Source:
    return Source(
        company=result.company,
        fiscal_year=result.fiscal_year,
        section=result.section,
        page=result.page,
        excerpt=_excerpt(excerpt, result.text),
        chunk_id=result.chunk_id,
    )


def parse_reply(reply: ChatMessage, context: BuiltContext) -> ParsedAnswer:
    try:
        output = _ToolOutput.model_validate(_tool_arguments(reply))
    except ValidationError as e:
        raise MalformedResponseError(f"Invalid {SUBMIT_ANSWER_TOOL_NAME} arguments: {e}") from e

    by_id = context.by_id()
    status = output.status
    answer = output.answer.strip()

    if status is not AnswerStatus.ANSWERED:
        # Refusals and "don't know" answers carry no citations.
        default = OUT_OF_SCOPE_MESSAGE if status is AnswerStatus.OUT_OF_SCOPE else INSUFFICIENT_CONTEXT_MESSAGE
        return ParsedAnswer(status=status, answer=answer or default, sources=[])

    sources: list[Source] = []
    seen: set[tuple[str, str]] = set()
    for item in output.sources:
        result = by_id.get(item.doc_id.strip())
        if result is None:
            logger.warning("Dropping source with unknown doc_id %r", item.doc_id)
            continue
        source = _to_source(result, item.excerpt)
        key = (source.chunk_id, source.excerpt)
        if key not in seen:
            seen.add(key)
            sources.append(source)

    if not sources or not answer:
        # No-source-no-answer: an unsupported answer may contain invented figures, so drop its text.
        logger.warning("Model answered without valid sources; downgrading to insufficient_context")
        return ParsedAnswer(status=AnswerStatus.INSUFFICIENT_CONTEXT, answer=INSUFFICIENT_CONTEXT_MESSAGE, sources=[])

    return ParsedAnswer(status=status, answer=answer, sources=sources)
