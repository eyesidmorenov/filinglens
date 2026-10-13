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
by Git. Section metrics are diagnostic proxies. Exact hit rate and MRR remain
`null` until reviewers populate `relevant_chunk_ids` with verified evidence
chunks after the definitive ETL output has been reindexed.

## Tests

From `search/`:

```powershell
pytest -q
```

Unit tests do not need Elasticsearch or a downloaded BGE model. They verify
the shared constants, exact filters, index guard, Contract 3 serialization,
RRF behavior, evaluation metrics, and the 75-question dataset.
