# Answer evaluation with RAGAS

> 🇪🇸 Versión en español: [README.es.md](README.es.md)

The search evaluation (`search/`) checks that the right chunk is found: 95% of the 150 labeled
questions have it in the top 5. This folder checks the step after it: **what Claude writes with
those chunks**.

| Metric | Question it answers | Range |
| --- | --- | --- |
| `faithfulness` | Is every claim in the answer supported by the chunks Claude was given? | 0 to 1 |
| `answer_relevancy` | Does the answer address the question that was asked? | 0 to 1 |
| `context_precision` | Are the chunks given to Claude useful for the answer, the best ones first? | 0 to 1 |

The judge is Claude (`claude-sonnet-5`, the model that answers) and the embeddings for
`answer_relevancy` are the BGE model the index already uses, so no OpenAI key is needed.

## Two steps

1. **Answers** (`ragas_eval/answers.py`, service `ragas-answers`). Runs in the API image, with the
   API's own pipeline: company and year detection, hybrid search (or the Yahoo snapshot) and
   tenk-answer, exactly as the chat. It keeps the full text of the chunks Claude saw; the API
   response only carries short excerpts.
2. **Scores** (`ragas_eval/score.py`, service `ragas`). Runs in its own image: RAGAS needs other
   versions of the Anthropic and LangChain libraries than tenk-answer, so the two steps never
   share an environment.

Only answers with status `answered` are scored. A refusal (`out_of_scope`) or an "I don't know"
(`insufficient_context`) has no claims to check; the summary counts every status apart.

## Run it

From the repository root, with Elasticsearch running, the index loaded and `ANTHROPIC_API_KEY`
in the root `.env`:

```bash
docker compose --profile ragas build ragas-answers ragas
docker compose --profile ragas run --rm ragas-answers      # step 1: 30 questions
docker compose --profile ragas run --rm ragas              # step 2: scores the latest run
```

A quick try first, then the whole set:

```bash
docker compose --profile ragas run --rm ragas-answers python -m ragas_eval.answers --limit 5
docker compose --profile ragas run --rm ragas-answers python -m ragas_eval.answers --limit 0   # all 150
```

The 30 questions are always the same: one per category in turn, in file order, so every category
is in the sample and two runs can be compared.

## Output

`data/eval/ragas/<date and time>/` (never committed):

| File | Content |
| --- | --- |
| `answers.jsonl` | One line per question: question, answer, status, chunk ids and text, tokens, latency |
| `scores.csv` | One row per scored answer with its three scores |
| `summary.json` | Averages, by category, status counts, company and year detection, tokens, judge model |

## Cost

Step 1 costs what the chat costs (about $0.012 per question). Step 2 calls Claude several times
per answer (claims, verdicts, generated questions, one call per chunk for context precision), so
30 questions cost a few dollars. Run 5 first.

## Tests

```bash
docker compose --profile ragas run --rm ragas python -m pytest -q
```

No Elasticsearch, Claude or RAGAS calls: sampling, the answer record, the summary and the files.
