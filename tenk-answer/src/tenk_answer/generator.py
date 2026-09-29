"""`AnswerGenerator`: question + retrieved documents -> cited `Answer`."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from typing import Any

import anthropic
from haystack import Document
from haystack.dataclasses import ChatMessage
from haystack.utils import Secret

from tenk_answer.context import TokenEstimator, build_context, estimate_tokens
from tenk_answer.errors import GenerationError, InvalidDocumentError, MalformedResponseError
from tenk_answer.parser import INSUFFICIENT_CONTEXT_MESSAGE, parse_reply
from tenk_answer.prompts import SUBMIT_ANSWER_TOOL, TOOL_CHOICE, build_messages, build_prompt_builder
from tenk_answer.types import Answer, AnswerStatus, SearchResult

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5"


def to_search_results(documents: Sequence[SearchResult | Document | dict[str, Any]]) -> list[SearchResult]:
    """Validate inputs at the boundary, accepting `SearchResult`, Haystack `Document` or Contract 3 dicts."""
    results: list[SearchResult] = []
    for doc in documents:
        if isinstance(doc, SearchResult):
            results.append(doc)
        elif isinstance(doc, Document):
            results.append(SearchResult.from_document(doc))
        elif isinstance(doc, dict):
            results.append(SearchResult.from_dict(doc))
        else:
            raise InvalidDocumentError(f"Unsupported document type: {type(doc).__name__}")
    return results


class AnswerGenerator:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: Secret = Secret.from_env_var("ANTHROPIC_API_KEY"),
        max_tokens: int = 1024,
        temperature: float | None = 0.0,
        max_context_tokens: int = 12_000,
        timeout: float = 30.0,
        max_retries: int = 2,
        generator: Any | None = None,
        token_estimator: TokenEstimator = estimate_tokens,
    ) -> None:
        """
        :param temperature: `None` omits the parameter (for models that don't accept it).
        :param generator: Any Haystack chat generator whose `run` accepts `messages`, `generation_kwargs` and
            `tools`. Defaults to an `AnthropicChatGenerator` built from the other arguments.
        :param token_estimator: Estimates tokens for the context budget. Default: characters / 4.
        """
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_context_tokens = max_context_tokens
        self.token_estimator = token_estimator
        if generator is None:
            from haystack_integrations.components.generators.anthropic import AnthropicChatGenerator

            generator = AnthropicChatGenerator(api_key=api_key, model=model, timeout=timeout, max_retries=max_retries)
        self.generator = generator
        self._prompt_builder = build_prompt_builder()

    def _generation_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"tool_choice": dict(TOOL_CHOICE), "max_tokens": self.max_tokens}
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        return kwargs

    def _call_model(self, messages: list[ChatMessage]) -> ChatMessage:
        try:
            result = self.generator.run(
                messages=messages, generation_kwargs=self._generation_kwargs(), tools=[SUBMIT_ANSWER_TOOL]
            )
        except (anthropic.AnthropicError, TimeoutError) as e:
            raise GenerationError(f"Answer generation failed: {type(e).__name__}: {e}") from e
        replies = result.get("replies") or []
        if not replies:
            raise MalformedResponseError("Chat generator returned no replies")
        reply: ChatMessage = replies[0]
        return reply

    def run(self, question: str, documents: Sequence[SearchResult | Document | dict[str, Any]]) -> Answer:
        start = time.perf_counter()

        def elapsed_ms() -> int:
            return round((time.perf_counter() - start) * 1000)

        if not question or not question.strip():
            raise ValueError("question must be a non-empty string")
        results = to_search_results(documents)
        context = build_context(results, self.max_context_tokens, self.token_estimator)

        if not context.documents:
            return Answer(
                status=AnswerStatus.INSUFFICIENT_CONTEXT,
                answer=INSUFFICIENT_CONTEXT_MESSAGE,
                sources=[],
                latency_ms=elapsed_ms(),
                model=self.model,
                usage={},
            )

        messages = build_messages(self._prompt_builder, documents=context.text, question=question.strip())
        reply = self._call_model(messages)
        parsed = parse_reply(reply, context)
        return Answer(
            status=parsed.status,
            answer=parsed.answer,
            sources=parsed.sources,
            latency_ms=elapsed_ms(),
            model=str(reply.meta.get("model") or self.model),
            usage=dict(reply.meta.get("usage") or {}),
        )
