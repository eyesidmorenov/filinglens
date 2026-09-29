# tenk-answer

Turns a question and already-retrieved 10-K chunks (Contract 3) into a cited answer (Contract 4), using Haystack 3 and Claude.
See `CLAUDE.md` for the product rules, contracts and design.

## Usage

```python
from haystack.utils import Secret
from tenk_answer import AnswerGenerator, SearchResult

gen = AnswerGenerator(model="claude-sonnet-5", api_key=Secret.from_env_var("ANTHROPIC_API_KEY"))
answer = gen.run(
    question="What are NVIDIA's main supply chain risks?",
    documents=[SearchResult.from_dict(hit) for hit in search_hits],  # or Haystack Documents
)
answer.status              # answered | insufficient_context | out_of_scope
answer.to_api_response()   # {"answer", "sources": [...], "latency_ms"}: exactly Contract 4
```

To use it inside a pipeline, place `AnswerComponent(AnswerGenerator(...))` right after the retriever. Connect `retriever.documents` to `answer.documents`.

## Development

Run every command from this folder:

```bash
uv sync
uv run pytest                    # offline unit tests (integration tests are deselected)
uv run pytest -m integration     # live API tests; need ANTHROPIC_API_KEY
uv run ruff check . && uv run mypy src
```

To run the live tests without putting the key in your shell history, put `ANTHROPIC_API_KEY=...` in `.env`, which is git-ignored:

```bash
uv run --env-file .env pytest -m integration
uv run --env-file .env python spikes/tool_choice_spike.py   # step-3 structured-output spike
```
