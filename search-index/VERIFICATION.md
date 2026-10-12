# Verification of the official index (DB-06 and DB-07)

Date: 2026-10-11. Package: `filinglens-cache_25-empresas_bge-base-en-v1.5_2026-10-08`.
Code: `eyesidmorenov/filinglens`, `main` at `c37b08b` (PR #10), cloned into a separate copy.
Server: Elasticsearch 8.15.3 (the one in the team's Compose), single node.

Everything was done with the **official loader** (`index/src/load.py`), following the package README.

## DB-06: definitive corpus indexed

```bash
docker compose up -d elasticsearch
docker compose --profile index run --rm index
```

Real output (75 lines like this one, 1 min 32 s in total):

```
Model BAAI/bge-base-en-v1.5 -> index 'filinglens-chunks' at http://elasticsearch:9200
  AAPL_2019_10K     202 chunks written,    0 old removed  (0 embedded now, 202 from cache)  over 512 tokens: 0
  ...
  VRTX_2021_10K     390 chunks written,    0 old removed  (0 embedded now, 390 from cache)  over 512 tokens: 0

Index 'filinglens-chunks' now holds 24284 chunks
```

Independent check (direct Elasticsearch queries against `data/chunks/_stats.csv`):

| Check | Result |
|---|---|
| Chunks in the index / sum of `_stats.csv` | 24,284 / 24,284 |
| Documents (`doc_id`) in the index / in `_stats.csv` | 75 / 75 |
| Documents whose total, text or table counts do not match | none |
| Tickers / tickers without exactly 3 years | 25 / none |
| Chunks per fiscal year | 2019: 8,263 · 2020: 8,142 · 2021: 7,879 |
| Text chunks / table chunks | 19,080 / 5,204 (same as `_stats.csv`) |
| Chunks without a vector | 0 |
| Documents with anything embedded during the load (should be 0) | 0 |
| Documents with chunks over 512 tokens | 0 |
| Vector | `dense_vector`, 768 dims, `cosine`, `int8_hnsw` |

`python -m search_index health` returns `status: ok` (cluster `yellow`); `stats` returns 24,284
chunks, 75 documents, 25 companies and 23 sections.

## DB-07: reindex and purge

| Operation | Command | Result |
|---|---|---|
| Identical reload (idempotency) | `... run --rm index` | 24,284; 0 embedded, 0 removed |
| Purging a document | move `AAPL_2019_10K.jsonl` aside and reload | `removed from the index (202 chunks)`; 24,082 remain and 0 of that document |
| Loading a single document | `python -m src.load --doc AAPL_2019_10K` | 202 written from cache; 24,284 |
| Full rebuild | `python -m src.load --recreate` | 24,284 |

## Search check from the README

`python -m src.load --check "What are Apple's supply chain risks?"` (real model, no filters):

```
--- BM25: What are Apple's supply chain risks?
  18.010  GILD_2021_10K_p21_c2  [Item 1A Risk Factors, p.21, text]  We are also aware of the existence of various suppliers...
  16.698  MDLZ_2021_10K_p26_c1  [Item 1A Risk Factors, p.26, text]  Any of these risks could materially and adversely affect...
  15.657  VRTX_2020_10K_p45_c1  [Item 1A Risk Factors, p.45, text]  Risks Related to Third-Party Manufacturing and Reliance...

--- Vector: What are Apple's supply chain risks?
  0.880  AAPL_2021_10K_p10_c3  [Item 1A Risk Factors, p.10, text]  Many of the Company's operations and facilities...
  0.878  AAPL_2021_10K_p12_c1  [Item 1A Risk Factors, p.12, text]  While the Company relies on its partners to adhere...
  0.877  AAPL_2021_10K_p14_c3  [Item 1A Risk Factors, p.14, text]  The Company depends on the performance of carriers...
```

Both retrievers respond. Without a filter, BM25 returns other companies (Apple's 10-Ks say "the
Company", not "Apple") while the vector search does find the right company. That is why `search/`
requires filtering by ticker and year.

## Observations for the authors of `index/` and `search/`

Measured against the real index, reproducing the query the Haystack BM25 retriever emits
(`multi_match` without `fields`, default `fuzziness` `AUTO`), with a ticker and year filter.

1. **BM25 also scores metadata, but it only shows on short queries.** The index does not set
   `index.query.default_field`, so `multi_match` searches every field. With an `AAPL` 2019 filter
   (202 chunks): the query `AAPL` matches all 202 (27 if limited to `content`), `Item 8` matches 199
   (95) and `10-K` matches 202 (43). **On the team's 75 evaluation questions nothing changes**: the
   same top-1 in 75/75 and 100% overlap in top-5 and top-50. It is a cheap hardening step (one line
   in the index `settings`), not an urgent one.
2. **`fuzziness` changes the ranking, but there is no evidence of which is better.** Going from
   `AUTO` to `0` changes the top-1 in 26 of 75 questions. With the only available proxy
   (`expected_sections`): top-1 in the expected section 40/75 (`AUTO`) versus 43/75 (`0`); some
   result in the top-5, 59 versus 60. The difference is within noise. Deciding needs real
   `relevant_chunk_ids`.
3. **The cluster stays `yellow`**: the index is created with 1 replica on a single node. The
   Compose healthcheck tolerates it; with `number_of_replicas: 0` it would be green.
4. **`company` is a slug** (`apple-inc`). Contract 3 and the API stub show `Apple Inc.`; `index/`
   has `company_name()` but only uses it in the embedding header.
5. **The real mapping adds `index_options: int8_hnsw`** (the ES 8.15 default). Neither the loader
   nor `search/` compares it, so it has no effect.

Neither the index nor the team repo was modified.
