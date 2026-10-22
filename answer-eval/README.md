# Answer evaluation with RAGAS

> 🇪🇸 Versión en español: [README.es.md](README.es.md)

The search evaluation (`search/`) checks that the right chunk is found: 95% of the 150 labeled
questions have it in the top 5. This folder checks the step after it: **what Claude writes with
those chunks**.

RAGAS can also write the test questions itself, from our own chunks, each with a reference answer
(Mariano's request, mentoring of 21/10). With a reference answer there are five metrics, the ones
of his `eval_ragas.py`; the labeled questions have none, so they get the three that don't need it.

| Metric | Question it answers | Needs a reference answer | Range |
| --- | --- | --- | --- |
| `context_recall` | Do the chunks given to Claude hold everything the reference answer needs? | Yes | 0 to 1 |
| `context_precision` | Are the chunks given to Claude useful for the answer, the best ones first? | No (uses it when there is one) | 0 to 1 |
| `faithfulness` | Is every claim in the answer supported by the chunks Claude was given? | No | 0 to 1 |
| `answer_relevancy` | Does the answer address the question that was asked? | No | 0 to 1 |
| `factual_correctness` | Does the answer agree with the reference answer? | Yes | 0 to 1 |

The judge is Claude (`claude-sonnet-5` unless `--model` or `RAGAS_MODEL` says otherwise) and the
embeddings for `answer_relevancy` are the BGE model the index already uses, so no OpenAI key is
needed. RAGAS always sends a `temperature` and `claude-sonnet-5` rejects it (HTTP 400), so the
judge leaves it out of the request (`common.ragas_models`).

`claude-haiku-5-5` is enough for RAGAS (questions and judge) and costs 20 times less, as Mariano's
script uses a small model (`gpt-4o-mini`). The answers being judged are still the chat's own,
written by `claude-sonnet-5`.

## Three steps

0. **Questions** (`ragas_eval/testset.py`, service `ragas`). RAGAS reads 8 chunks of each of 10
   filings of different companies (Items 1, 1A, 3, 7, 7A, 8 and 9A), builds its knowledge graph
   with Claude (summaries, themes, entities) and writes single-hop questions, each with its
   reference answer. A single-hop question comes from one chunk, so we know its company and
   year: the chat filters by both and doesn't compare filings. The questions are written as our
   user writes them (an equity analyst, correct grammar, medium or long); by default RAGAS also
   mixes misspelled ones. Only the companies of the evaluation set are used (the 50 of the v5
   package).
1. **Answers** (`ragas_eval/answers.py`, service `ragas-answers`). Runs in the API image, with the
   API's own pipeline: company and year detection, hybrid search (or the Yahoo snapshot) and
   tenk-answer, exactly as the chat. It keeps the full text of the chunks Claude saw; the API
   response only carries short excerpts. RAGAS questions don't always name the company or the
   year, so they go in with those of the filing they were written from.
2. **Scores** (`ragas_eval/score.py`, service `ragas`). Runs in its own image, as step 0: RAGAS
   needs other versions of the Anthropic and LangChain libraries than tenk-answer, so the steps
   that use RAGAS never share an environment with the API.

Only answers with status `answered` are scored. A refusal (`out_of_scope`) or an "I don't know"
(`insufficient_context`) has no claims to check; the summary counts every status apart.

## Run it

From the repository root, with Elasticsearch running, the index loaded and `ANTHROPIC_API_KEY`
in the root `.env`. Each person runs it with the key in their own `.env` (never committed), and
the calls are billed to that key.

```bash
docker compose --profile ragas build ragas-answers ragas
```

**With the questions RAGAS writes** (20 by default):

```bash
docker compose --profile ragas run --rm ragas python -m ragas_eval.testset --model claude-haiku-5-5        # step 0
docker compose --profile ragas run --rm ragas-answers python -m ragas_eval.answers --testset <run folder>   # step 1
docker compose --profile ragas run --rm ragas python -m ragas_eval.score --model claude-haiku-5-5          # step 2
```

Step 0 prints the run folder (for example `2026-10-21_2300`). Read its `testset.csv` before
step 1: a question that makes no sense is cheaper to drop there (delete its line in
`testset.jsonl`). A quick try first: `--n 3 --filings 1`.

**With the labeled questions:**

```bash
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
| `testset.jsonl` | Step 0, one line per question: question, reference answer and chunks, company, year, section and source chunk |
| `testset.csv` | The same questions and reference answers, to review by hand |
| `testset_info.json` | Filings and chunks used, model and generation tokens |
| `answers.jsonl` | One line per question: question, answer, status, chunk ids and text, tokens, latency (and the reference answer, if any) |
| `scores.csv` | One row per scored answer with its scores (five, or three without a reference answer) |
| `summary.json` | Averages, by category, status counts, company and year detection, tokens, judge model and judge tokens |

For RAGAS questions, the category is the section of the chunk each one was written from.

## Cost

Step 1 costs what the chat costs (about $0.012 per question). Steps 0 and 2 call Claude many
times: step 0 per chunk (summaries, themes, entities) and per question; step 2 per answer
(claims, verdicts, generated questions, one call per chunk for context precision).

Measured with 3 questions of Apple's 2020 10-K (21/10): the judge cost $0.34 with
`claude-sonnet-5` and $0.02 with `claude-haiku-5-5`, with similar scores. For 20 questions, all
three steps cost about $2.90 with `claude-sonnet-5` for RAGAS and about $0.40 with
`claude-haiku-5-5`, most of it the chat's own answers. Run 3 first.

## Tests

```bash
docker compose --profile ragas run --rm ragas python -m pytest -q
```

No Elasticsearch, Claude or RAGAS calls: sampling, the choice of filings and chunks, tracing a
RAGAS question to its filing, the answer record, the metric names, the summary and the files.
