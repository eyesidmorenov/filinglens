from __future__ import annotations

import json
from typing import Any

import anthropic
import httpx
import jsonschema
import pytest
from haystack.dataclasses import ChatMessage
from helpers import FakeChatGenerator, FakeStreamingChatGenerator, tool_reply

from tenk_answer import AnswerGenerator, AnswerStatus, GenerationError, MalformedResponseError, SearchResult
from tenk_answer.prompts import SUBMIT_ANSWER_TOOL_NAME

NVDA = "NVDA_2024_10K_p18_c2"
NVDA_EXPORT = "NVDA_2024_10K_p24_c1"

PAYLOAD: dict[str, Any] = {
    "status": "answered",
    "answer": "NVIDIA relies on TSMC [1], and export controls limit sales to China [2].",
    "sources": [
        {"doc_id": "D1", "excerpt": "we rely on Taiwan Semiconductor Manufacturing Company Limited"},
        {"doc_id": "D2", "excerpt": "export controls restricting the sale"},
    ],
}


def json_reply(payload: dict[str, Any]) -> ChatMessage:
    return ChatMessage.from_assistant(json.dumps(payload), meta={"model": "claude-fake", "usage": {"x": 1}})


def split(text: str, size: int = 7) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def streaming_fake(payload: dict[str, Any], **kwargs: Any) -> FakeStreamingChatGenerator:
    return FakeStreamingChatGenerator(reply=json_reply(payload), pieces=split(json.dumps(payload)), **kwargs)


def collect(gen: AnswerGenerator, question: str, documents: list[Any]) -> tuple[Any, list[str]]:
    tokens: list[str] = []
    answer = gen.stream(question, documents, on_token=tokens.append)
    return answer, tokens


def test_streams_the_answer_text_then_returns_the_same_answer_as_run(
    results: dict[str, SearchResult], contract4_schema: dict[str, Any]
) -> None:
    docs = [results[NVDA], results[NVDA_EXPORT]]
    gen = AnswerGenerator(generator=streaming_fake(PAYLOAD), structured_output=True)
    answer, tokens = collect(gen, "What supply risks does NVIDIA face?", docs)

    assert len(tokens) > 1
    assert "".join(tokens) == PAYLOAD["answer"]

    expected = AnswerGenerator(generator=FakeChatGenerator(json_reply(PAYLOAD)), structured_output=True).run(
        "What supply risks does NVIDIA face?", docs
    )
    assert answer.model_dump(exclude={"latency_ms"}) == expected.model_dump(exclude={"latency_ms"})
    assert answer.status is AnswerStatus.ANSWERED
    assert answer.model == "claude-fake"
    jsonschema.validate(answer.to_api_response(), contract4_schema)


def test_sends_the_same_request_as_run_plus_a_callback(results: dict[str, SearchResult]) -> None:
    fake = streaming_fake(PAYLOAD)
    AnswerGenerator(generator=fake, structured_output=True, max_tokens=512).stream("Risks?", [results[NVDA]], print)
    plain = FakeChatGenerator(json_reply(PAYLOAD))
    AnswerGenerator(generator=plain, structured_output=True, max_tokens=512).run("Risks?", [results[NVDA]])

    sent, expected = fake.calls[0], plain.calls[0]
    assert sent["generation_kwargs"] == expected["generation_kwargs"]
    assert sent["tools"] is None
    assert sent["messages"] == expected["messages"]
    assert callable(sent["streaming_callback"])


def test_forced_tool_call_mode_streams_the_tool_arguments(results: dict[str, SearchResult]) -> None:
    reply = tool_reply(answer=PAYLOAD["answer"], sources=PAYLOAD["sources"])
    fake = FakeStreamingChatGenerator(reply=reply, pieces=split(json.dumps(PAYLOAD)), as_tool_call=True)
    answer, tokens = collect(AnswerGenerator(generator=fake), "q", [results[NVDA], results[NVDA_EXPORT]])

    assert "".join(tokens) == PAYLOAD["answer"]
    assert [t.name for t in fake.calls[0]["tools"]] == [SUBMIT_ANSWER_TOOL_NAME]
    assert [s.chunk_id for s in answer.sources] == [NVDA, NVDA_EXPORT]


def test_final_answer_renumbers_markers_the_preview_did_not(results: dict[str, SearchResult]) -> None:
    payload = {
        "status": "answered",
        "answer": "Export controls limit sales [2].",
        "sources": [{"doc_id": "D9", "excerpt": "x"}, {"doc_id": "D1", "excerpt": "export controls"}],
    }
    gen = AnswerGenerator(generator=streaming_fake(payload), structured_output=True)
    answer, tokens = collect(gen, "q", [results[NVDA_EXPORT]])

    assert "".join(tokens) == "Export controls limit sales [2]."
    assert answer.answer == "Export controls limit sales [1]."


def test_answer_without_valid_sources_is_replaced_after_streaming(results: dict[str, SearchResult]) -> None:
    payload = {"status": "answered", "answer": "NVIDIA made $1T.", "sources": []}
    gen = AnswerGenerator(generator=streaming_fake(payload), structured_output=True)
    answer, tokens = collect(gen, "q", [results[NVDA]])

    assert "".join(tokens) == "NVIDIA made $1T."
    assert answer.status is AnswerStatus.INSUFFICIENT_CONTEXT
    assert "$1T" not in answer.answer
    assert answer.sources == []


def test_no_documents_short_circuits_without_tokens() -> None:
    fake = streaming_fake(PAYLOAD)
    answer, tokens = collect(AnswerGenerator(generator=fake, structured_output=True), "q", [])
    assert answer.status is AnswerStatus.INSUFFICIENT_CONTEXT
    assert tokens == []
    assert fake.calls == []


def test_empty_question_rejected(results: dict[str, SearchResult]) -> None:
    with pytest.raises(ValueError):
        AnswerGenerator(generator=streaming_fake(PAYLOAD)).stream("  ", [results[NVDA]], print)


_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize("error", [anthropic.APITimeoutError(request=_REQUEST), TimeoutError("timed out")])
def test_api_errors_mid_stream_are_wrapped(results: dict[str, SearchResult], error: Exception) -> None:
    fake = streaming_fake(PAYLOAD, error=error)
    tokens: list[str] = []
    with pytest.raises(GenerationError) as info:
        AnswerGenerator(generator=fake, structured_output=True).stream("q", [results[NVDA]], tokens.append)
    assert info.value.__cause__ is error
    assert tokens  # some text had already streamed


def test_malformed_final_reply_raises(results: dict[str, SearchResult]) -> None:
    fake = FakeStreamingChatGenerator(reply=ChatMessage.from_assistant("{not json"), pieces=["{not json"])
    with pytest.raises(MalformedResponseError):
        AnswerGenerator(generator=fake, structured_output=True).stream("q", [results[NVDA]], print)
