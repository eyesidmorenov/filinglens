# Deliverable 3: index (chunks + embeddings into Elasticsearch)

Loads the chunks produced by the ETL (`data/chunks/*.jsonl`) into Elasticsearch, each with its BGE embedding, so the search lane can query them by keywords (BM25) and by meaning (vectors).

```
data/chunks/*.jsonl ──► context header + BGE embeddings ──► Elasticsearch index "filinglens-chunks"
                                    │
                            data/embeddings/ (cache)
```

## How to run

From the repository root, with the ETL output in `data/chunks/`:

```bash
docker compose up -d elasticsearch
docker compose --profile index build index
docker compose --profile index run --rm index                                   # load every document
docker compose --profile index run --rm index python -m src.load --doc AAPL_2019_10K
docker compose --profile index run --rm index python -m src.load --recreate     # rebuild the index
docker compose --profile index run --rm --no-deps index python -m src.load --embed-only   # embeddings only, no Elasticsearch
docker compose --profile index run --rm index pytest -q                         # tests
```

Test a question through both retrievers after loading:

```bash
docker compose --profile index run --rm index python -m src.load --doc AAPL_2019_10K --check "What are Apple's main risk factors?"
```

The first run downloads the model (about 440 MB) into the `hf_models` Docker volume.

## Two steps: compute the embeddings, then load them

Computing embeddings is the slow part (about 1.5 chunks per second on a laptop CPU; 3,231 chunks took 39 minutes). Loading into Elasticsearch takes seconds once the embeddings exist. The loader can do both at once, or the two steps can run on different machines:

| Step | Command | Needs Elasticsearch | Output |
| --- | --- | --- | --- |
| 1. Compute embeddings | `python -m src.load --embed-only` | No | Cache in `data/embeddings/` |
| 2. Create the index and load | `python -m src.load` | Yes | Index `filinglens-chunks`, filled from the cache |

Step 2 creates the index with the mapping it needs (see "What is stored") and reads every vector from the cache, so nothing is recomputed. Whoever runs step 2 only needs `data/chunks/` and `data/embeddings/`, for example by unzipping a shared cache into the repository root.

### Optional: step 1 on a free GPU (Google Colab)

The pipeline is plain Python run in Docker, with no notebooks. Colab is only a temporary machine with a GPU to run step 1, and only the cache comes back. Tested on 2026-10-08: a T4 embedded the 24,284 chunks of the 25 companies in about 10 minutes (41 chunks/s, against 1.5 on a laptop CPU), and the vectors match the CPU ones (cosine 1.000000 on 30 random chunks).

1. Locally, after the ETL, from the repository root (works on Windows, macOS and Linux):
   ```bash
   python -c "import shutil; shutil.make_archive('chunks', 'zip', '.', 'data/chunks')"
   ```
   `chunks.zip` keeps the `data/chunks/` path inside.
2. In Colab: *Runtime → Change runtime type → T4 GPU*, then upload `chunks.zip` in the Files panel.
3. First cell: get the code and the libraries, and unzip the chunks.
   ```bash
   !ls -l chunks.zip
   !nvidia-smi --query-gpu=name --format=csv
   !git clone -q https://github.com/eyesidmorenov/filinglens.git
   !pip install -q haystack-ai==3.3.0 elasticsearch-haystack==6.4.1 sentence-transformers==6.1.0 sentence-transformers-haystack==0.2.0
   !unzip -q chunks.zip -d filinglens
   !ls filinglens/data/chunks/*.jsonl | wc -l
   ```
   Check that the zip has the same size as the local file, that the GPU is a `Tesla T4`, and the number of chunk files. Colab already has PyTorch with GPU support: do not install `index/requirements.txt` there, because it pins the CPU build. To test a branch before it is merged, add `-b <branch>` to `git clone`.
4. Second cell: compute the embeddings. A warning about `HF_TOKEN` can be ignored.
   ```bash
   !cd filinglens/index && DATA_DIR=/content/filinglens/data EMBED_BATCH_SIZE=64 python -m src.load --embed-only
   ```
   It ends with `Cache ready: N chunks, N embedded in ... s`.
5. Third cell: pack the cache. Then refresh the Files panel and download `embeddings.zip`. Keep the tab open until the download ends: Colab deletes its files when the session closes.
   ```bash
   !cd filinglens && zip -qr /content/embeddings.zip data/embeddings
   ```
6. Unzip `embeddings.zip` into the repository root and run step 2. Every document should print `0 embedded now`.

**The index lives on your machine.** Elasticsearch runs locally from `docker-compose.yml`, and its data is in the `filinglens_es_data` Docker volume. Nothing in `data/` goes to GitHub, so every teammate (and the demo laptop) builds the index with the ETL and these commands.

## What the loader guarantees

- **The index matches the chunk files exactly.** After writing a document, any older chunk of that document is deleted, so re-chunking leaves no orphans. A full load (no `--doc`) also removes documents that no longer have a `.jsonl`, for example a filing the ETL now skips.
- **Embeddings are cached by content.** `data/embeddings/<model>/<doc_id>.npz` stores one vector per exact embedded text. Reloading only embeds new or changed chunks; a reload served fully from cache doesn't even load the model.
- **A wrong index is never reused silently.** If `filinglens-chunks` exists with a different mapping (another model's dimensions, Haystack's default mapping, a missing field), the loader stops and asks for `--recreate`.

## Settings shared with search and the API

Search and the API container **must use exactly these values**, or retrieval fails without any error.

| Setting | Value | Where |
| --- | --- | --- |
| Model | `BAAI/bge-base-en-v1.5` | `EMBEDDING_MODEL` |
| Dimensions | 768 | `EMBEDDING_DIMS` |
| Normalization | `normalize_embeddings=True` on chunks and queries | code |
| Query prefix | `"Represent this sentence for searching relevant passages: "` on **queries only** | `src/config.py` |
| Similarity | cosine | index mapping |
| Index | `filinglens-chunks` | `ES_INDEX` |
| Elasticsearch | `http://elasticsearch:9200` inside Compose | `ELASTICSEARCH_URL` |

Query embedding in the search pipeline (Haystack 3):

```python
from haystack_integrations.components.embedders.sentence_transformers import SentenceTransformersTextEmbedder

embedder = SentenceTransformersTextEmbedder(
    model="BAAI/bge-base-en-v1.5",
    prefix="Represent this sentence for searching relevant passages: ",
    normalize_embeddings=True,
)
```

Nothing else is needed on the query side: the context header below is only added to chunks.

## What is stored

Each chunk becomes a Haystack `Document`, the shape `tenk-answer` reads as Contract 3:

| Document | Comes from | Elasticsearch type |
| --- | --- | --- |
| `id` | `chunk_id` | document id |
| `content` | `text` | `text` with the English analyzer (BM25 matches "risks" with "risk") |
| `embedding` | BGE, computed on the context header + `text` | `dense_vector`, 768 dims, cosine |
| `meta.section`, `meta.company`, `meta.ticker`, `meta.doc_id`, `meta.doc_type` | chunk | `keyword` (filterable) |
| `meta.section_title` | added here from `section`: "Item 1A" → "Risk Factors" | `keyword` (filterable) |
| `meta.chunk_type` | chunk's `content_type` (`text` or `table`) | `keyword` (filterable) |
| `meta.page`, `meta.fiscal_year` | chunk | `integer` (filterable) |

Filter by company and year with `ticker` and `fiscal_year`, never by company name: three different companies are called "Independent Bank".

**Context header.** Each chunk is embedded as `Apple Inc (AAPL) | Fiscal 2019 | Item 1A Risk Factors` followed by its text, so its vector also knows whose filing and which section it comes from. The header is not stored: `content`, excerpts and citations show the chunk text only.

**Why `chunk_type` and not `content_type`:** Haystack reserves `content_type` (it was a `Document` field in Haystack 1.x). A meta key with that name is stored nested under `meta` in Elasticsearch, where filters can't reach it. The loader renames it, and fails loudly if any other chunk field clashes with a reserved name.

## Notes

- BGE truncates texts over 512 tokens without warning. The ETL sizes chunks in tokens with a margin for the header; the loader still reports, per document, how many embedded texts pass the limit.
- NVIDIA's financial statements are in Item 15, not Item 8. Intel 2020 and 2021 have `section: "Unknown"` (see `etl/README.md`).
