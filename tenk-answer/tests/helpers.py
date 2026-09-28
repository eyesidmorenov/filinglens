"""Offline test doubles shared by the unit tests."""

from __future__ import annotations

from typing import Any

from haystack import component
from haystack.dataclasses import ChatMessage, ToolCall


def tool_reply(
    status: str = "answered",
    answer: str = "An answer.",
    sources: list[dict[str, str]] | None = None,
    *,
    arguments: Any = None,
    tool_name: str = "submit_answer",
    meta: dict[str, Any] | None = None,
) -> ChatMessage:
    """A canned assistant reply carrying a submit_answer tool call."""
    args = arguments if arguments is not None else {"status": status, "answer": answer, "sources": sources or []}
    return ChatMessage.from_assistant(
        tool_calls=[ToolCall(tool_name=tool_name, arguments=args, id="toolu_fake")],
        meta=meta or {"model": "claude-fake", "usage": {"input_tokens": 100, "output_tokens": 20}},
    )


@component
class FakeChatGenerator:
    """Offline stand-in for a Haystack chat generator. Records every call."""

    def __init__(self, reply: ChatMessage | None = None, error: Exception | None = None) -> None:
        self.reply = reply if reply is not None else tool_reply()
        self.error = error
        self.calls: list[dict[str, Any]] = []

    @component.output_types(replies=list[ChatMessage])
    def run(
        self,
        messages: list[ChatMessage],
        generation_kwargs: dict[str, Any] | None = None,
        tools: list[Any] | None = None,
    ) -> dict[str, list[ChatMessage]]:
        self.calls.append({"messages": messages, "generation_kwargs": generation_kwargs, "tools": tools})
        if self.error is not None:
            raise self.error
        return {"replies": [self.reply]}

    @property
    def system_prompt(self) -> str:
        return self.calls[-1]["messages"][0].text or ""

    @property
    def user_prompt(self) -> str:
        return self.calls[-1]["messages"][-1].text or ""
