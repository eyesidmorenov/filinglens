from __future__ import annotations

import pytest
from haystack.dataclasses import ChatMessage
from helpers import tool_reply

from tenk_answer import AnswerStatus, MalformedResponseError, SearchResult
from tenk_answer.context import BuiltContext, build_context
from tenk_answer.parser import EXCERPT_FALLBACK_CHARS, INSUFFICIENT_CONTEXT_MESSAGE, parse_reply


@pytest.fixture
def ctx(results: dict[str, SearchResult]) -> BuiltContext:
    # D1 = AAPL 2024, D2 = AAPL 2023
    return build_context([results["AAPL_2024_10K_p21_c1"], results["AAPL_2023_10K_p20_c1"]], 10_000)


def test_excerpt_substring_is_kept(ctx: BuiltContext) -> None:
    parsed = parse_reply(tool_reply(sources=[{"doc_id": "D1", "excerpt": " $391,035 million "}]), ctx)
    assert parsed.sources[0].excerpt == "$391,035 million"


def test_excerpt_not_in_chunk_falls_back_to_prefix(ctx: BuiltContext) -> None:
    parsed = parse_reply(tool_reply(sources=[{"doc_id": "D1", "excerpt": "Revenue was $1 trillion"}]), ctx)
    chunk = ctx.documents[0].result.text
    assert parsed.status is AnswerStatus.ANSWERED
    assert parsed.sources[0].excerpt == chunk[:EXCERPT_FALLBACK_CHARS].strip()
    assert parsed.sources[0].excerpt in chunk


def test_unknown_doc_id_is_dropped(ctx: BuiltContext, caplog: pytest.LogCaptureFixture) -> None:
    sources = [{"doc_id": "D9", "excerpt": "x"}, {"doc_id": "D2", "excerpt": "$383,285 million"}]
    parsed = parse_reply(tool_reply(sources=sources), ctx)
    assert [s.chunk_id for s in parsed.sources] == ["AAPL_2023_10K_p20_c1"]
    assert "D9" in caplog.text


@pytest.mark.parametrize(
    "sources",
    [[], [{"doc_id": "D9", "excerpt": "x"}], [{"doc_id": "chunk_id_leak", "excerpt": "x"}]],
)
def test_answered_without_valid_sources_is_downgraded(ctx: BuiltContext, sources: list[dict[str, str]]) -> None:
    parsed = parse_reply(tool_reply(answer="Revenue was $500 billion.", sources=sources), ctx)
    assert parsed.status is AnswerStatus.INSUFFICIENT_CONTEXT
    assert parsed.sources == []
    assert "500" not in parsed.answer  # unsupported figures never reach the user
    assert parsed.answer == INSUFFICIENT_CONTEXT_MESSAGE


def test_duplicate_sources_are_collapsed(ctx: BuiltContext) -> None:
    src = {"doc_id": "D1", "excerpt": "$391,035 million"}
    assert len(parse_reply(tool_reply(sources=[src, src]), ctx).sources) == 1


@pytest.mark.parametrize("status", ["insufficient_context", "out_of_scope"])
def test_non_answered_statuses_carry_no_sources(ctx: BuiltContext, status: str) -> None:
    parsed = parse_reply(tool_reply(status=status, answer="Polite.", sources=[{"doc_id": "D1", "excerpt": "x"}]), ctx)
    assert parsed.status == status
    assert parsed.answer == "Polite."
    assert parsed.sources == []


@pytest.mark.parametrize("status", ["insufficient_context", "out_of_scope"])
def test_empty_refusal_text_gets_default(ctx: BuiltContext, status: str) -> None:
    parsed = parse_reply(tool_reply(status=status, answer="  "), ctx)
    assert parsed.answer
    assert "single company" in parsed.answer or "specific company" in parsed.answer  # says what it can answer


def test_string_arguments_are_parsed(ctx: BuiltContext) -> None:
    reply = tool_reply(arguments='{"status": "answered", "answer": "A", "sources": [{"doc_id": "D1", "excerpt": "x"}]}')
    assert parse_reply(reply, ctx).status is AnswerStatus.ANSWERED


@pytest.mark.parametrize(
    "reply",
    [
        ChatMessage.from_assistant("plain text, no tool", meta={"finish_reason": "stop"}),
        ChatMessage.from_assistant(meta={"finish_reason": "length"}),  # truncated tool call dropped by integration
        tool_reply(tool_name="other_tool"),
        tool_reply(arguments={"status": "maybe", "answer": "A", "sources": []}),
        tool_reply(arguments={"answer": "A", "sources": []}),
        tool_reply(arguments={"status": "answered", "answer": "A", "sources": [{"doc_id": "D1"}]}),
        tool_reply(arguments="{not json"),
        tool_reply(arguments="[1, 2]"),
    ],
)
def test_malformed_tool_output_raises(ctx: BuiltContext, reply: ChatMessage) -> None:
    with pytest.raises(MalformedResponseError):
        parse_reply(reply, ctx)
