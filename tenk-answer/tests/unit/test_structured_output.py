from __future__ import annotations

import json

from haystack.dataclasses import ChatMessage
from helpers import FakeChatGenerator

from tenk_answer import AnswerGenerator, AnswerStatus, SearchResult
from tenk_answer.prompts import SUBMIT_ANSWER_SCHEMA

NVDA = "NVDA_2024_10K_p18_c2"


def json_reply(payload: dict) -> ChatMessage:
    return ChatMessage.from_assistant(json.dumps(payload), meta={"model": "claude-fake", "usage": {}})


def test_structured_output_sends_the_schema_and_no_tool(results: dict[str, SearchResult]) -> None:
    payload = {"status": "answered", "answer": "Supply chain risks.", "sources": [{"doc_id": "D1", "excerpt": "x"}]}
    fake = FakeChatGenerator(reply=json_reply(payload))
    answer = AnswerGenerator(generator=fake, structured_output=True).run("Risks?", [results[NVDA]])

    sent = fake.calls[-1]
    assert sent["tools"] is None
    assert "tool_choice" not in sent["generation_kwargs"]
    assert sent["generation_kwargs"]["output_config"]["format"]["schema"] == SUBMIT_ANSWER_SCHEMA
    assert "submit_answer tool" not in fake.system_prompt
    assert answer.status is AnswerStatus.ANSWERED
    assert [s.chunk_id for s in answer.sources] == [NVDA]


def test_default_keeps_the_forced_tool_call(results: dict[str, SearchResult]) -> None:
    fake = FakeChatGenerator()
    AnswerGenerator(generator=fake).run("Risks?", [results[NVDA]])

    sent = fake.calls[-1]
    assert sent["tools"] and "tool_choice" in sent["generation_kwargs"]
    assert "output_config" not in sent["generation_kwargs"]
