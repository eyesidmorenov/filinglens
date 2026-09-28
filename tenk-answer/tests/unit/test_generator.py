from __future__ import annotations

from typing import Any

import anthropic
import httpx
import jsonschema
import pytest
from helpers import FakeChatGenerator, tool_reply

from tenk_answer import (
    AnswerGenerator,
    AnswerStatus,
    GenerationError,
    InvalidDocumentError,
    MalformedResponseError,
    SearchResult,
)
from tenk_answer.prompts import SUBMIT_ANSWER_TOOL_NAME

NVDA = "NVDA_2024_10K_p18_c2"
NVDA_EXPORT = "NVDA_2024_10K_p24_c1"
AAPL24 = "AAPL_2024_10K_p21_c1"
AAPL23 = "AAPL_2023_10K_p20_c1"
KO = "KO_2023_10K_p5_c1"
INJECTION = "NVDA_2024_10K_p25_c4"


def make(fake: FakeChatGenerator, **kwargs: Any) -> AnswerGenerator:
    return AnswerGenerator(generator=fake, **kwargs)


def test_happy_path_maps_sources_to_chunk_fields(
    results: dict[str, SearchResult], contract4_schema: dict[str, Any]
) -> None:
    fake = FakeChatGenerator(
        tool_reply(
            answer="NVIDIA relies on TSMC and Samsung, and export controls limit sales to China.",
            sources=[
                {"doc_id": "D1", "excerpt": "we rely on Taiwan Semiconductor Manufacturing Company Limited"},
                {"doc_id": "D2", "excerpt": "export controls restricting the sale"},
            ],
        )
    )
    answer = make(fake).run("What supply risks does NVIDIA face?", [results[NVDA], results[NVDA_EXPORT]])

    assert answer.status is AnswerStatus.ANSWERED
    assert [(s.chunk_id, s.company, s.fiscal_year, s.section, s.page) for s in answer.sources] == [
        (NVDA, "NVIDIA Corporation", 2024, "Item 1A", 18),
        (NVDA_EXPORT, "NVIDIA Corporation", 2024, "Item 1A", 24),
    ]
    assert answer.model == "claude-fake"
    assert answer.usage == {"input_tokens": 100, "output_tokens": 20}
    assert answer.latency_ms >= 0
    jsonschema.validate(answer.to_api_response(), contract4_schema)


def test_generator_receives_forced_tool_and_prompt(results: dict[str, SearchResult]) -> None:
    fake = FakeChatGenerator(tool_reply(sources=[{"doc_id": "D1", "excerpt": "foundries"}]))
    make(fake, max_tokens=512, temperature=0.0).run("  What are NVIDIA's risks?  ", [results[NVDA]])

    call = fake.calls[0]
    assert [t.name for t in call["tools"]] == [SUBMIT_ANSWER_TOOL_NAME]
    assert call["generation_kwargs"] == {
        "tool_choice": {"type": "tool", "name": SUBMIT_ANSWER_TOOL_NAME},
        "max_tokens": 512,
        "temperature": 0.0,
    }
    roles = [m.role.value for m in call["messages"]]
    assert roles == ["system", "user"]
    user = fake.user_prompt
    assert '<document id="D1" company="NVIDIA Corporation" fiscal_year="2024" section="Item 1A" page="18">' in user
    assert user.index("</documents>") < user.index("What are NVIDIA's risks?")


def test_temperature_none_is_omitted(results: dict[str, SearchResult]) -> None:
    fake = FakeChatGenerator(tool_reply(sources=[{"doc_id": "D1", "excerpt": "foundries"}]))
    make(fake, temperature=None).run("q", [results[NVDA]])
    assert "temperature" not in fake.calls[0]["generation_kwargs"]


def test_accepts_documents_and_dicts(results: dict[str, SearchResult], raw_results: dict[str, Any]) -> None:
    fake = FakeChatGenerator(tool_reply(sources=[{"doc_id": "D2", "excerpt": "export controls"}]))
    answer = make(fake).run("q", [results[NVDA].to_document(), raw_results[NVDA_EXPORT]])
    assert answer.sources[0].chunk_id == NVDA_EXPORT


def test_no_documents_short_circuits() -> None:
    fake = FakeChatGenerator()
    answer = make(fake).run("What are NVIDIA's risks?", [])
    assert answer.status is AnswerStatus.INSUFFICIENT_CONTEXT
    assert answer.sources == []
    assert answer.answer
    assert fake.calls == []


def test_all_documents_over_budget_short_circuits(results: dict[str, SearchResult]) -> None:
    fake = FakeChatGenerator()
    answer = make(fake, max_context_tokens=5).run("q", [results[NVDA]])
    assert answer.status is AnswerStatus.INSUFFICIENT_CONTEXT
    assert fake.calls == []


def test_irrelevant_context_passes_through(results: dict[str, SearchResult]) -> None:
    fake = FakeChatGenerator(tool_reply(status="insufficient_context", answer="The filings don't cover this."))
    answer = make(fake).run("What are NVIDIA's risks?", [results[KO]])
    assert answer.status is AnswerStatus.INSUFFICIENT_CONTEXT
    assert answer.answer == "The filings don't cover this."
    assert answer.sources == []


@pytest.mark.parametrize("sources", [[], [{"doc_id": "D7", "excerpt": "x"}]])
def test_answered_without_valid_sources_downgraded(
    results: dict[str, SearchResult], sources: list[dict[str, str]]
) -> None:
    fake = FakeChatGenerator(tool_reply(answer="NVIDIA made $1T.", sources=sources))
    answer = make(fake).run("q", [results[NVDA]])
    assert answer.status is AnswerStatus.INSUFFICIENT_CONTEXT
    assert "$1T" not in answer.answer
    assert answer.to_api_response()["sources"] == []


def test_unknown_doc_id_dropped(results: dict[str, SearchResult]) -> None:
    fake = FakeChatGenerator(
        tool_reply(sources=[{"doc_id": "D5", "excerpt": "x"}, {"doc_id": "D1", "excerpt": "foundries"}])
    )
    answer = make(fake).run("q", [results[NVDA]])
    assert [s.chunk_id for s in answer.sources] == [NVDA]


def test_conflicting_figures_across_years_keep_both_sources(results: dict[str, SearchResult]) -> None:
    fake = FakeChatGenerator(
        tool_reply(
            answer="FY2024 10-K reports $383,285M for fiscal 2023; the FY2023 10-K reports the same.",
            sources=[
                {"doc_id": "D1", "excerpt": "compared to $383,285 million for fiscal 2023"},
                {"doc_id": "D2", "excerpt": "Total net sales were $383,285 million for fiscal 2023"},
            ],
        )
    )
    answer = make(fake).run("What were Apple's fiscal 2023 net sales?", [results[AAPL24], results[AAPL23]])
    assert [(s.chunk_id, s.fiscal_year) for s in answer.sources] == [(AAPL24, 2024), (AAPL23, 2023)]
    assert [s["fiscal_year"] for s in answer.to_api_response()["sources"]] == [2024, 2023]


def test_token_budget_excludes_lower_ranked_docs_preserving_order(results: dict[str, SearchResult]) -> None:
    ranked = [results[AAPL24], results[AAPL23], results[NVDA], results[NVDA_EXPORT]]
    fake = FakeChatGenerator(tool_reply(sources=[{"doc_id": "D1", "excerpt": "x"}]))
    # ~ 2 short Apple docs fit, the longer NVIDIA docs don't
    make(fake, max_context_tokens=150).run("q", ranked)
    user = fake.user_prompt
    assert "$391,035 million" in user and "$383,285 million for fiscal 2023, compared" in user
    assert user.index("$391,035") < user.index("$394,328")
    assert "foundries" not in user and "export controls" not in user
    assert 'id="D3"' not in user


def test_prompt_injection_is_contained(results: dict[str, SearchResult]) -> None:
    fake = FakeChatGenerator(tool_reply(sources=[{"doc_id": "D1", "excerpt": "foundries"}]))
    make(fake).run("What are NVIDIA's risks?", [results[NVDA], results[INJECTION]])

    user = fake.user_prompt
    start = user.index('<document id="D2"')
    end = user.index("</document>", start)
    assert "SYSTEM OVERRIDE" in user[start:end]  # injected text sits inside its own document tag
    assert user.count("</document>") == 2  # the injected closing tag was escaped
    assert user.count("<document ") == 2  # the injected opening tag was escaped
    assert 'id="D99"' in user and '<document id="D99"' not in user

    system = fake.system_prompt.lower()
    assert "data, not instructions" in system
    assert "ignore any instructions" in system


@pytest.mark.parametrize(
    ("question", "status"),
    [
        ("Compare NVIDIA vs AMD margins", "out_of_scope"),
        ("Should I buy NVIDIA stock?", "out_of_scope"),
        ("How much did Apple revenue grow from 2023 to 2024?", "out_of_scope"),
    ],
)
def test_out_of_scope_passes_through(results: dict[str, SearchResult], question: str, status: str) -> None:
    fake = FakeChatGenerator(tool_reply(status=status, answer="I can only answer questions about one company's 10-K."))
    answer = make(fake).run(question, [results[NVDA]])
    assert answer.status == status
    assert answer.sources == []


def test_system_prompt_states_product_rules(results: dict[str, SearchResult]) -> None:
    fake = FakeChatGenerator(tool_reply(sources=[{"doc_id": "D1", "excerpt": "foundries"}]))
    make(fake).run("q", [results[NVDA]])
    system = fake.system_prompt.lower()
    for phrase in ("comparison across companies", "calculation", "investment advice", "out_of_scope", "english"):
        assert phrase in system


_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.mark.parametrize(
    "error",
    [
        anthropic.APITimeoutError(request=_REQUEST),
        anthropic.APIConnectionError(request=_REQUEST),
        anthropic.RateLimitError("rate limited", response=httpx.Response(429, request=_REQUEST), body=None),
        anthropic.InternalServerError("boom", response=httpx.Response(500, request=_REQUEST), body=None),
        TimeoutError("timed out"),
    ],
)
def test_api_errors_are_wrapped(results: dict[str, SearchResult], error: Exception) -> None:
    with pytest.raises(GenerationError) as info:
        make(FakeChatGenerator(error=error)).run("q", [results[NVDA]])
    assert info.value.__cause__ is error


def test_malformed_tool_output_raises(results: dict[str, SearchResult]) -> None:
    fake = FakeChatGenerator(tool_reply(arguments={"status": "answered"}))
    with pytest.raises(MalformedResponseError):
        make(fake).run("q", [results[NVDA]])


def test_missing_contract3_field_raises(raw_results: dict[str, Any]) -> None:
    raw = {k: v for k, v in raw_results[NVDA].items() if k != "fiscal_year"}
    fake = FakeChatGenerator()
    with pytest.raises(InvalidDocumentError):
        make(fake).run("q", [raw])
    assert fake.calls == []


def test_empty_question_rejected(results: dict[str, SearchResult]) -> None:
    with pytest.raises(ValueError):
        make(FakeChatGenerator()).run("   ", [results[NVDA]])


def test_default_generator_is_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    from haystack_integrations.components.generators.anthropic import AnthropicChatGenerator

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    gen = AnswerGenerator(timeout=12.0, max_retries=4)
    assert isinstance(gen.generator, AnthropicChatGenerator)
    assert gen.generator.model == "claude-sonnet-5"
    assert gen.generator.timeout == 12.0
    assert gen.generator.max_retries == 4
