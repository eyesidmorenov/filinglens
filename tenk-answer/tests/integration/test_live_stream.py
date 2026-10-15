"""Live streaming tests against the Anthropic API. Run with: uv run pytest -m integration

Confirms that `AnthropicChatGenerator` really streams with `output_config` structured output (the API's mode),
and that the streamed text matches the final answer once [n] markers are left aside.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

import jsonschema
import pytest

from tenk_answer import AnswerGenerator, AnswerStatus, SearchResult

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set"),
]

NVDA_RISKS = ["NVDA_2024_10K_p18_c2", "NVDA_2024_10K_p24_c1"]
MARKERS = re.compile(r"\s*\[\d+\]")


@pytest.mark.parametrize("structured_output", [True, False], ids=["output_config", "forced_tool"])
def test_streams_tokens_before_the_reply_completes(
    results: dict[str, SearchResult], contract4_schema: dict[str, Any], structured_output: bool
) -> None:
    gen = AnswerGenerator(
        model=os.environ.get("TENK_ANSWER_MODEL", "claude-sonnet-5"),
        temperature=None,
        max_tokens=2048,
        structured_output=structured_output,
    )
    arrivals: list[tuple[float, str]] = []
    start = time.perf_counter()
    answer = gen.stream(
        "What are NVIDIA's main supply chain and regulatory risks?",
        [results[i] for i in NVDA_RISKS],
        on_token=lambda text: arrivals.append((time.perf_counter() - start, text)),
    )
    total = time.perf_counter() - start

    assert answer.status is AnswerStatus.ANSWERED
    jsonschema.validate(answer.to_api_response(), contract4_schema)
    assert len(arrivals) > 1, "the answer arrived in a single piece: the reply was not streamed"
    assert arrivals[0][0] < total, "no text arrived before the reply was complete"
    streamed = "".join(text for _, text in arrivals)
    assert MARKERS.sub("", streamed).strip() == MARKERS.sub("", answer.answer).strip()
