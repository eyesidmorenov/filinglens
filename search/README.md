# Hybrid retrieval and evaluation

This lane reads the existing `filinglens-chunks` index and never creates,
rebuilds, deletes, or writes to it. It combines filtered BM25 and vector
retrieval with reciprocal rank fusion (RRF), then emits the fields expected by
the generation lane.

```text
question + ticker + fiscal_year
            |              |
          BM25      BGE query embedding
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

`evaluation/questions.json` contains 75 English questions: three for each of
the 25 indexed companies, with 25 questions per fiscal year (2019-2021).
It intentionally includes:

- 25 numeric/table questions;
- 25 broader business, risk, and operating-results questions;
- 25 short-section probes for Items 3, 7A, and 9A to expose ETL section-label
  errors.

Run all three retrieval modes from `search/`:

```powershell
python -m src.evaluation
```

The report is written to `data/evaluation/search-report.json`, which is ignored
by Git. Section metrics are diagnostic proxies; the exact metrics count a hit
only when a returned chunk is one of the question's `relevant_chunk_ids`.

### Exact labels

`relevant_chunk_ids` are filled by `src/labels.py` from evidence in the chunks,
never from a retriever's ranking (727 ids for the 75 questions):

| Category | A chunk is relevant when |
| --- | --- |
| Numeric (25) | a reported figure sits in the same table row or sentence as its metric (Apple 2020: 274,515 next to "net sales"). Figures were read from each filing's income statement. |
| Legal proceedings (9), market risk (8) | it belongs to Item 3 or Item 7A |
| Controls (8) | it is in Item 9A and states the conclusion ("concluded", "were effective") |
| Broader (25) | it is in the expected section and mentions at least two of the question's topics |

Chunk ids change whenever the ETL re-chunks a filing, so labels belong to one
chunk package (2026-10-13, 24,737 chunks). After loading a new package, run
`python -m src.labels` from `search/`: it rewrites `evaluation/questions.json`
and refuses to write if any question finds no evidence.

First run with exact labels (2026-10-13 package, top 5):

| Mode | Exact hit rate | Exact MRR | Section hit rate | Section MRR |
| --- | --- | --- | --- | --- |
| BM25 | 0.61 | 0.42 | 0.85 | 0.67 |
| Vector | 0.89 | 0.70 | 0.95 | 0.89 |
| Hybrid | 0.89 | 0.63 | 0.96 | 0.83 |

## Tests

From `search/`:

```powershell
pytest -q
```

Unit tests do not need Elasticsearch or a downloaded BGE model. They verify
the shared constants, exact filters, index guard, Contract 3 serialization,
RRF behavior, evaluation metrics, and the 75-question dataset.
