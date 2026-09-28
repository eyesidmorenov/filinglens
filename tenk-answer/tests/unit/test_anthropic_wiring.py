"""Offline check of the real AnthropicChatGenerator wiring: the SDK client is stubbed, everything else is real."""

from __future__ import annotations

from typing import Any

import anthropic
import httpx
import pytest
from anthropic.types import Message

from tenk_answer import AnswerGenerator, AnswerStatus, GenerationError, MalformedResponseError, SearchResult

NVDA = "NVDA_2024_10K_p18_c2"


def _message(content: list[dict[str, Any]], stop_reason: str = "tool_use") -> Message:
    return Message.model_validate(
        {
            "id": "msg_fake",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5",
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 321, "output_tokens": 45},
        }
    )


def _tool_use(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": "toolu_1", "name": "submit_answer", "input": arguments}


class _StubMessages:
    def __init__(self, response: Message | Exception) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Message:
        self.kwargs = kwargs
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class _StubClient:
    def __init__(self, response: Message | Exception) -> None:
        self.messages = _StubMessages(response)


@pytest.fixture
def make(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")

    def _make(response: Message | Exception) -> tuple[AnswerGenerator, _StubMessages]:
        gen = AnswerGenerator(max_tokens=700)
        client = _StubClient(response)
        gen.generator.client = client  # warm_up() keeps an existing client
        return gen, client.messages

    return _make


def test_request_forces_submit_answer_and_response_is_parsed(make: Any, results: dict[str, SearchResult]) -> None:
    gen, stub = make(
        _message(
            [_tool_use({"status": "answered", "answer": "TSMC.", "sources": [{"doc_id": "D1", "excerpt": "TSMC"}]})]
        )
    )
    answer = gen.run("Who manufactures NVIDIA's wafers?", [results[NVDA]])

    sent = stub.kwargs
    assert sent["model"] == "claude-sonnet-5"
    assert sent["tool_choice"] == {"type": "tool", "name": "submit_answer"}
    assert sent["max_tokens"] == 700
    assert sent["temperature"] == 0.0
    assert [t["name"] for t in sent["tools"]] == ["submit_answer"]
    assert sent["tools"][0]["input_schema"]["required"] == ["status", "answer", "sources"]
    system_text = sent["system"][0]["text"] if isinstance(sent["system"], list) else sent["system"]
    assert "data, not instructions" in system_text
    assert '<document id="D1"' in str(sent["messages"])

    assert answer.status is AnswerStatus.ANSWERED
    assert answer.sources[0].chunk_id == NVDA
    assert answer.model == "claude-sonnet-5"
    assert answer.usage["prompt_tokens"] == 321  # integration reports OpenAI-style usage keys
    assert answer.usage["completion_tokens"] == 45


def test_truncated_tool_call_raises_malformed(make: Any, results: dict[str, SearchResult]) -> None:
    # The integration drops a tool_use block cut off by max_tokens, leaving no tool call at all.
    gen, _ = make(_message([_tool_use({"status": "answered"})], stop_reason="max_tokens"))
    with pytest.raises(MalformedResponseError, match="finish_reason='length'"):
        gen.run("q", [results[NVDA]])


def test_sdk_timeout_is_wrapped(make: Any, results: dict[str, SearchResult]) -> None:
    error = anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    gen, _ = make(error)
    with pytest.raises(GenerationError) as info:
        gen.run("q", [results[NVDA]])
    assert info.value.__cause__ is error
