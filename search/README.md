# Hybrid retrieval and evaluation

This lane reads the existing `filinglens-chunks` index and never creates,
rebuilds, deletes, or writes to it. It combines filtered BM25 and vector
retrieval with reciprocal rank fusion (RRF), then emits the fields expected by
the generation lane.

```text
question + ticker + fiscal_year
            |              |
   BM25 (question without  BGE query embedding
   company and year)       (full question)
            |              |
            +------ RRF ---+
                    |
             Contract 3 chunks
```

## Shared contract

| Setting | Value |
| --- | --- |
| Elasticsearch index | `filinglens-chunks` |
| Haystack store | `ElasticsearchDocumentStore` |
| Embedding model | `BAAI/bge-base-en-v1.5` |
| Dimensions | 768 |
| Query prefix | `Represent this sentence for searching relevant passages: ` |
| Chunk prefix | none |
| Mandatory filters | `ticker` and `fiscal_year` |
| Indexed document | `id=chunk_id`, `content=text`, remaining fields in `meta` |

The embedder adds the query prefix. Pass a plain English question; do not add
the prefix in the caller. Search verifies the existing mapping and document
count before querying, so it fails with a clear message instead of silently
creating an incompatible empty index.

**BM25 searches the question without the company and the year.** Both are
already filters, so in BM25 they only add noise: "Apple" and "2019" appear in
hundreds of the filing's chunks and pulled up notes that repeat them, ahead of
the passage that answers. `keyword_query()` removes the year ("in fiscal 2020",
"FY2021"), the ticker (in capitals only: FAST is a company, "fast" is a word)
and the company as the question writes it ("Apple's", "Cadence Design
Systems'", "Kraft Heinz's"), taken from the filing's official `company_name`,
which every candidate carries. The vector search keeps the full question. If
nothing would be left, BM25 gets the full question. Known limit: a question
that says "Facebook" about the 2021 filing, already named "Meta Platforms",
keeps the word.

By default each retriever contributes 50 candidates, matching the evaluation
run, and RRF returns the best five. Override these values with
`SEARCH_CANDIDATE_TOP_K` and `SEARCH_TOP_K` or the command-line options.

## Local setup without Docker

The only data that must already exist locally is a populated Elasticsearch
index produced by the `index/` lane. The PDFs, JSONL chunks, embeddings, model
cache, and Elasticsearch data are deliberately excluded from Git.

From the repository root in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r .\search\requirements.txt
```

Start the local Elasticsearch instance that contains `filinglens-chunks`, then
run one search:

```powershell
$env:ELASTICSEARCH_URL = "http://localhost:9200"
Set-Location .\search
python -m src.retrieval `
  --question "What main risk factors did Apple identify in fiscal 2019?" `
  --ticker AAPL --year 2019 --mode hybrid
```

The JSON output contains the Contract 3 fields `chunk_id`, `text`, `score`,
`section`, `page`, `company`, and `fiscal_year`.

## Evaluation set

`evaluation/questions.json` contains 150 English questions: three for each of
the 50 indexed companies, with 50 questions per fiscal year (2019-2021).
Q01-Q75 cover the first 25 companies; Q76-Q150 the 25 added on 2026-10-16,
with the same categories and proportions. When companies are added, their
questions are appended to this same file (Q151 onwards), so questions and
labels are never duplicated. It intentionally includes:

- 50 numeric/table questions;
- 50 broader business, risk, and operating-results questions;
- 50 short-section probes for Items 3, 7A, and 9A to expose ETL section-label
  errors.

Run all three retrieval modes from `search/`:

```powershell
python -m src.evaluation
```

The report is written to `data/evaluation/search-report.json`, which is ignored
by Git. The evaluator accepts the number of questions present in the selected
file, so a larger set does not require a code change:

```powershell
python -m src.evaluation --expected-count 150
```

`--expected-count` is an optional completeness guard. The report includes
global metrics, breakdowns by company, fiscal year, category and difficulty,
and the exact ids of questions with empty results, filter failures, section
misses or exact-chunk misses. Section metrics are diagnostic proxies; the exact
metrics count a hit only when a returned chunk is one of the question's
`relevant_chunk_ids`.

### Exact labels

`relevant_chunk_ids` are filled by `src/labels.py` from evidence in the chunks,
never from a retriever's ranking (1,473 ids for the 150 questions):

| Category | A chunk is relevant when |
| --- | --- |
| Numeric (50) | a reported figure sits in the same table row or sentence as its metric (Apple 2020: 274,515 next to "net sales"). Figures were read from each filing's income statement (Cerner 2019 and Logitech 2021 do not include the statements in the 10-K: selected financial data and MD&A). |
| Legal proceedings (18), market risk (16) | it belongs to Item 3 or Item 7A |
| Controls (16) | it is in Item 9A and states the conclusion ("concluded", "were effective") |
| Broader (50) | it is in the expected section and mentions at least two of the question's topics |

Chunk ids change whenever the ETL re-chunks a filing, so labels belong to one
chunk package (v5, 2026-10-19, 50,785 chunks). After loading a new package, run
`python -m src.labels` from `search/`: it rewrites `evaluation/questions.json`
and refuses to write if any question finds no evidence.

First run with exact labels (2026-10-13 package, top 5):

| Mode | Exact hit rate | Exact MRR | Section hit rate | Section MRR |
| --- | --- | --- | --- | --- |
| BM25 | 0.61 | 0.42 | 0.85 | 0.67 |
| Vector | 0.89 | 0.70 | 0.95 | 0.89 |
| Hybrid | 0.89 | 0.63 | 0.96 | 0.83 |

150 questions, 50 companies (v5 package, 2026-10-19, top 5). "Before" is the
hybrid with the full question in BM25; "after" leaves out the company and the
year (`keyword_query()`):

| Mode | Exact hit rate | Exact MRR | Section hit rate |
| --- | --- | --- | --- |
| BM25, before | 0.60 | 0.40 | 0.83 |
| BM25, after | 0.81 | 0.57 | 0.97 |
| Vector | 0.93 | 0.76 | 0.99 |
| Hybrid, before | 0.89 | 0.64 | 0.98 |
| **Hybrid, after** | **0.95** | **0.78** | **0.99** |

The hybrid now finds the exact chunk more often than vectors alone, on both
halves of the set (first 25 companies: 71/75 against 69/75; added 25: 71/75
against 71/75). By category, the hybrid gains in numeric questions (39 to 46 of
50), business (16 to 17 of 18) and legal proceedings (17 to 18 of 18), and no
category loses. Also tried, offline on the same candidates: more weight for
vectors in RRF (small gains on one half only, so not adopted), 10 to 100
candidates per retriever and dropping `Unknown` chunks (no clear change).

## Tests

From `search/`:

```powershell
pytest -q
```

Unit tests do not need Elasticsearch or a downloaded BGE model. They verify
the shared constants, exact filters, index guard, Contract 3 serialization,
RRF behavior, the BM25 keyword query, scalable evaluation, diagnostic
breakdowns, and the 150-question dataset.
