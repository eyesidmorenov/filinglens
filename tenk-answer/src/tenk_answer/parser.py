"""Turns the model's `submit_answer` tool call into statuses and `Source`s, enforcing no-source-no-answer."""

from __future__ import annotations

import json
import logging
import re
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
    if not calls and not reply.tool_calls and reply.text and reply.text.lstrip().startswith("{"):
        # Structured output: the same fields arrive as a JSON text block
        try:
            parsed = json.loads(reply.text)
        except json.JSONDecodeError as e:
            raise MalformedResponseError(f"Reply is not valid JSON: {e}") from e
        if not isinstance(parsed, dict):
            raise MalformedResponseError(f"Reply must be a JSON object, got {type(parsed).__name__}")
        return parsed
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
    position: dict[tuple[str, str], int] = {}
    # renumber[i] = final 1-based position of the model's i-th source, or None if it was dropped
    renumber: dict[int, int | None] = {}
    for i, item in enumerate(output.sources, start=1):
        result = by_id.get(item.doc_id.strip())
        if result is None:
            logger.warning("Dropping source with unknown doc_id %r", item.doc_id)
            renumber[i] = None
            continue
        source = _to_source(result, item.excerpt)
        key = (source.chunk_id, source.excerpt)
        if key not in position:
            sources.append(source)
            position[key] = len(sources)
        renumber[i] = position[key]

    if not sources or not answer:
        # No-source-no-answer: an unsupported answer may contain invented figures, so drop its text.
        logger.warning("Model answered without valid sources; downgrading to insufficient_context")
        return ParsedAnswer(status=AnswerStatus.INSUFFICIENT_CONTEXT, answer=INSUFFICIENT_CONTEXT_MESSAGE, sources=[])

    return ParsedAnswer(status=status, answer=renumber_markers(answer, renumber), sources=sources)


# "[1]", "[2, 3]" or "[1,2]": a group of citation markers written by the model
_MARKER = re.compile(r"\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]")


def renumber_markers(answer: str, renumber: dict[int, int | None]) -> str:
    """Point the model's [n] markers at the final source list.

    Markers of dropped sources disappear, duplicates collapse ([1][1] -> [1]), and a bracketed number that is not
    one of the model's sources (e.g. "[2019]") is left untouched.
    """

    removed = "\x00"  # placeholder, so only the spaces left by a removed marker are cleaned up

    def replace(match: re.Match[str]) -> str:
        numbers = [int(n) for n in match.group(1).split(",")]
        if not all(n in renumber for n in numbers):
            return match.group(0)
        final = sorted({m for n in numbers if (m := renumber[n]) is not None})
        return "".join(f"[{m}]" for m in final) or removed

    text = _MARKER.sub(replace, answer)
    # Adjacent groups can repeat a number after renumbering: "[1][1]" -> "[1]"
    text = re.sub(r"(\[\d+\])(?:\1)+", r"\1", text)
    # "claim [removed]." -> "claim."
    text = re.sub(rf"[ \t]*{removed}", "", text)
    return text.strip()
