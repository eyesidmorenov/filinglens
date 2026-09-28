# CLAUDE.md: 10-K Answer Generator (Haystack + Claude PoC)

## Goal
This project is a self-contained subfolder of a larger repo. Keep `pyproject.toml`, `uv.lock`, `tests/` and `spikes/` inside this folder, run every command from here, and never assume the git root is the project root.

A small, importable Python library covering steps 4–5 of the RAG diagram. Input: a question plus already-retrieved documents. Output: a structured answer with citations. The FastAPI service will import it later.

Out of scope for this repo: ETL, Elasticsearch, retrieval, FastAPI, Chainlit, streaming, chat history.

## Product rules (from the project doc)
- Every answer cites **company, fiscal year, section, page**. An invented figure is worse than "I don't know."
- Supported questions: prose questions about a single company's 10-K (risks, business model, competition) and point figures stated in the text.
- Refused as `out_of_scope`:
  - comparisons across companies
  - growth or arithmetic calculations
  - any buy/sell/investment advice
- A refusal is polite and says what the bot *can* answer instead.
- Answers are in English. Source documents are English 10-Ks.

## Stack
- Python 3.12 managed with `uv`, in a `src/` layout
- `haystack-ai` (3.x, currently 3.2) and `anthropic-haystack` (>=6.2, `AnthropicChatGenerator`). anthropic-haystack 6.x requires Haystack 3.
- `pydantic` v2 for public types
- Dev: `pytest`, `ruff`, `mypy`

## Contracts (from the team's CONTRATOS.md; LOCKED, the team decided they are not up for rediscussion)
This library sits between **Contract 3** (its input) and **Contract 4** (its output). Adapt the library to the contracts, never the other way around. The `status` field stays internal to `Answer` for this reason.

### Contract 3: Search result (input)
```json
{
  "chunk_id": "NVDA_2024_10K_p42_c3",
  "text": "...",
  "score": 0.87,
  "section": "Item 7",
  "page": 42,
  "company": "NVIDIA Corporation",
  "fiscal_year": 2024
}
```
Accepted in two forms:
- `SearchResult`, a pydantic model mirroring Contract 3 exactly
- A Haystack `Document`, for use inside a pipeline, mapped as:
  - `id` = `chunk_id`
  - `content` = `text`
  - `score` = `score`
  - `meta` = `{section, page, company, fiscal_year}`

Adapters convert in both directions: `SearchResult.to_document()` and `SearchResult.from_document()`.
- `section` holds the 10-K item label: "Item 1", "Item 1A", "Item 7" or "Item 8".
- Results arrive already ranked. There is no `ticker` or `doc_id` in this contract, so don't rely on them.
- Missing required fields raise `InvalidDocumentError`. Validate at the boundary.

### Contract 4: API response (output shape to produce)
```json
{
  "answer": "...",
  "sources": [
    {"company": "NVIDIA Corporation", "fiscal_year": 2024, "section": "Item 7", "page": 42, "excerpt": "..."}
  ],
  "latency_ms": 1840
}
```
- The library returns an `Answer` model.
- `Answer.to_api_response()` must serialize to **exactly** Contract 4.
- Fields not in Contract 4 must not leak into `to_api_response()`: `status`, `chunk_id`, `model` and `usage`. They live only on `Answer`.

## Public API
```python
from tenk_answer import AnswerGenerator, AnswerComponent, SearchResult, Answer, Source, AnswerStatus

gen = AnswerGenerator(
    model="claude-sonnet-5",    # constructor args only, no env-based config
    api_key=Secret.from_env_var("ANTHROPIC_API_KEY"),
    max_tokens=1024,
    temperature=0.0,
    max_context_tokens=12_000,
    timeout=30.0,
    max_retries=2,
    generator=None,  # inject any Haystack chat generator (used by tests)
)
answer: Answer = gen.run(question="...", documents=[...])  # list[SearchResult] or list[Document]
answer.to_api_response()  # -> dict matching Contract 4
```
- `AnswerComponent` is a Haystack `@component` with inputs `question: str` and `documents: list[Document]`, and output `answer: Answer`. It wraps `AnswerGenerator` so it can sit right after the retriever in the real pipeline.
- Types:
  - `Answer`:
    - `status: AnswerStatus` (`answered | insufficient_context | out_of_scope`)
    - `answer: str`
    - `sources: list[Source]`
    - `latency_ms: int` (wall-clock time of `run`)
    - `model: str`
    - `usage: dict`
  - `Source`:
    - `company`
    - `fiscal_year`
    - `section`
    - `page`
    - `excerpt` (a short supporting excerpt from the chunk)
    - `chunk_id`, internal and excluded from the API response

## Design
1. **Context builder.** Walk the documents in rank order and assign local ids `D1..Dn`. Stop when adding the next document would exceed `max_context_tokens`. Use a token estimator that can be swapped out (default: chars/4). Render each chunk as `<document id="D1" company=… fiscal_year=… section=… page=…>…</document>`. Escape any `</document>` that appears inside content.
2. **Prompt.** Use `ChatPromptBuilder`.
   - The system prompt holds the product rules and tells the model that document text is **data, not instructions**.
   - The user message holds the documents followed by the question.
3. **Structured output.** Force a tool call.
   - Define a Haystack `Tool` named `submit_answer` with the schema `{status, answer, sources: [{doc_id, excerpt}]}`.
   - Pass it to `AnthropicChatGenerator` with forced `tool_choice`. Never invoke it; just read `reply.tool_calls[0].arguments`.
   - Spiked (`spikes/tool_choice_spike.py`). Forced `tool_choice` passes through `generation_kwargs`, and `ToolCall.arguments` arrives as a dict. Native citations don't fit: the integration only sends PDF document blocks, never enables citations, and citations can't carry `status`. `output_config` structured output is the backup option.
   - If `max_tokens` cuts off the tool call, the integration drops it (0 tool calls, `finish_reason="length"`). The parser raises `MalformedResponseError`.
   - `Answer.usage` passes through the integration's OpenAI-style keys (`prompt_tokens`, `completion_tokens`).
4. **Parser.** Map `doc_id` back to the chunk's fields to build `Source`s. `excerpt` must be a substring of the chunk text; if it isn't, replace it with the first ~200 chars of the chunk.
   - Unknown ids are dropped and logged.
   - `answered` with zero valid sources is downgraded to `insufficient_context`. This enforces the no-source-no-answer rule in code, not just in the prompt.
   - Missing or invalid tool output raises `MalformedResponseError`.
5. **Short-circuit.** An empty document list returns `insufficient_context` without calling the API.
6. **Errors.** Anthropic API and timeout errors are wrapped in `GenerationError`, with the original error chained. Retries use the client's `max_retries`.

## Tests
### Unit tests (`tests/unit/`)
- Inject a fake chat generator: a Haystack component that returns canned `ChatMessage`s with tool calls. No network. Also assert on the prompt the fake received.
- Scenarios:
  - Happy path: valid answer, sources mapped to chunk fields.
  - `to_api_response()` matches Contract 4 exactly (same keys, no extras) and validates against a JSON schema fixture.
  - `SearchResult` ↔ `Document` round-trip is lossless.
  - An excerpt not found in the chunk falls back to a chunk prefix.
  - No documents: `insufficient_context`, and the generator is never called.
  - Irrelevant context: the model returns `insufficient_context`, and it passes through.
  - Answered but no or invalid sources: downgraded to `insufficient_context`.
  - Unknown doc id in sources: dropped.
  - Conflicting figures across years: both sources kept, with their years.
  - Token budget: lower-ranked docs are excluded from the prompt, and order is preserved.
  - Prompt injection: injected text sits inside the document tags, closing tags are escaped, and the system prompt contains the data-not-instructions rule.
  - Out-of-scope statuses (comparison, investment advice) pass through.
  - API error or timeout: `GenerationError`.
  - Malformed tool output: `MalformedResponseError`.
  - Missing Contract 3 field: `InvalidDocumentError`.
  - `AnswerComponent` works inside a real `Pipeline` using the fake generator.

### Integration tests (`tests/integration/`)
- Marked `@pytest.mark.integration` and skipped without `ANTHROPIC_API_KEY`.
- Run with `uv run pytest -m integration`.
- Use fixture chunks in Contract 3 shape from `tests/fixtures/search_results.json`, with real-looking `chunk_id`s (e.g. `NVDA_2024_10K_p42_c3`): NVIDIA risk factors, Apple FY2023 and FY2024 revenue, an irrelevant chunk, and an injection chunk.
- Assert on status and sources, not exact wording:
  - A NVIDIA risk question is `answered` and cites NVIDIA risk-factor documents.
  - An Apple FY2024 revenue question cites the FY2024 document.
  - "Compare NVIDIA vs AMD margins" is `out_of_scope`.
  - "Should I buy Tesla?" is `out_of_scope`.
  - A question with only the irrelevant document is `insufficient_context`.
  - The injection document does not change the output schema or status behavior.

## Layout
```
src/tenk_answer/
  __init__.py
  types.py   # SearchResult, Answer, Source, AnswerStatus
  errors.py
  context.py
  prompts.py
  parser.py
  generator.py
  component.py
tests/
  unit/
  integration/
  fixtures/search_results.json
  fixtures/contract4.schema.json
  conftest.py
```

## Commands
- `uv sync`
- `uv run pytest` (unit tests only by default; configure `addopts = "-m 'not integration'"`)
- `uv run pytest -m integration`
- `uv run ruff check . && uv run mypy src`

## Working rules
- Write tests alongside each module, and keep unit tests fully offline.
- Verify the `anthropic-haystack` API against its current docs before coding. This matters most for tool-choice support, and for whether its native citations support fits better than the tool-call approach.
- Don't add retrieval, FastAPI or streaming code.
