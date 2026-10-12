# search-index

A **read-only** companion for the FilingLens Elasticsearch index (10-K chatbot, AnyoneAI Team 3).
It provides what the rest of the repo does not have yet:

- `admin.health()`: the real status of the cluster and the index, for `/health`.
- `admin.stats()`: counts by company, year, section and chunk type, for `/stats` and QA.
- `build_filters()`: filters by company, ticker, fiscal year and section (a value or a list).

It does not load data or search: `index/` (the official loader) and `search/` (hybrid retrieval)
already do that. This module **never creates, modifies or deletes** anything in Elasticsearch.
The verification of the official corpus is in [`VERIFICATION.md`](VERIFICATION.md).

## Installation

Python ≥ 3.10. It only depends on `elasticsearch` (8.x) and `pydantic`.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m search_index --help
```

## Configuration

Same variable names as the rest of the repo (see `.env.example`):

| Variable | Default | Use |
|---|---|---|
| `ELASTICSEARCH_URL` | `http://localhost:9200` | Inside Compose: `http://elasticsearch:9200` |
| `ES_INDEX` | `filinglens-chunks` | Index created by the team loader |
| `EMBEDDING_DIMS` | `768` | Dimensions of `bge-base-en-v1.5`; compared with the index |

`IndexSettings.from_env(prefix="SEARCH_")` reads the same variables with a prefix. API keys
(`ELASTIC_API_KEY`, `ELASTIC_API_KEY_ID`) are read from the environment only when connecting and are
never stored.

## Usage

```bash
python -m search_index health   # JSON; exits 1 unless the status is "ok"
python -m search_index stats    # JSON with the counts
```

```python
from fastapi import FastAPI, Response
from search_index import IndexSettings, admin

settings = IndexSettings.from_env()
app = FastAPI()

@app.get("/health")
def health(response: Response):
    report = admin.health(settings)          # never raises; 2 s timeouts
    response.status_code = 200 if report["status"] == "ok" else 503
    return report

@app.get("/stats")
def stats():
    return admin.stats(settings)             # IndexCompatibilityError if the index is unusable
```

`health()` returns `{"status", "cluster_status", "index_exists", "compatible", "detail"}`:

- `ok`: cluster green or yellow, the index exists, its mapping is compatible and it has chunks.
- `degraded`: Elasticsearch answers but the index is missing, the mapping is not the loader's, the
  dimensions do not match, the index is empty or the cluster is red. `detail` says what and how
  to fix it.
- `down`: Elasticsearch does not answer.

`stats()` returns `{"index", "total_chunks", "total_documents", "by_company", "by_ticker",
"by_fiscal_year", "by_section", "by_chunk_type", "embedding_dims"}`. `total_documents` counts
distinct `doc_id` values.

"Compatible" means the mapping has the fields that search and stats read, with their types, as
`index/src/documents.py` creates them. The index does not record which model produced its vectors,
so the model cannot be checked, only the 768 dimensions.

### Filters

```python
from search_index import build_filters

build_filters(ticker="AAPL", fiscal_year=2019)
build_filters(ticker=["AAPL", "NVDA"], section="Item 1A")   # a list becomes "in"
```

It returns a filter in Haystack syntax (or `None` with no arguments), valid for
`ElasticsearchBM25Retriever` and `ElasticsearchEmbeddingRetriever`. An empty string or list raises
`ValueError`. Today `search/` always requires a ticker and a year and builds its own filter; using
this one would mean extending `HybridRetriever.run`.

## Tests

```bash
pytest -m "not integration"            # no Docker, no network
docker compose up -d elasticsearch     # from the repo root: ES 8.15.3
pytest -m integration
pytest --cov
ruff check .
```

The integration tests create their own `test_filinglens_<uuid8>` index with a literal copy of the
loader's mapping (`tests/es_helpers.py`), refuse to touch any name that does not start with
`test_`, and delete it when they finish. The data in `tests/fixtures/` is synthetic.
