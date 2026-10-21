# Verification of the official index (DB-06 and DB-07)

Date: 2026-10-20. Package: 50 companies, `BAAI/bge-base-en-v1.5`, version 2026-10-19 (v5).
Code: `eyesidmorenov/filinglens`, `main` at `2af6af6` (PR #37).
Server: Elasticsearch 8.15.3, single node.

Everything was loaded with the **official loader** (`index/src/load.py`), following the package README.
The index already held the previous package (25 companies, 24,284 chunks), so this also checks an
in-place update.

## DB-06: definitive corpus indexed

```bash
docker compose up -d elasticsearch
docker compose --profile index build index   # see the note below
docker compose --profile index run --rm index
```

Real output (150 lines like this one):

```
Model BAAI/bge-base-en-v1.5 -> index 'filinglens-chunks' at http://elasticsearch:9200
  ...
  DXCM_2020_10K     397 chunks written,    0 old removed  (0 embedded now, 397 from cache)  over 512 tokens: 0
  ...
Index 'filinglens-chunks' now holds 50785 chunks
```

Independent check (`elastic_search/scripts/verify.py`: direct Elasticsearch queries against
`data/chunks/_stats.csv`):

| Check | Result |
|---|---|
| Chunks in the index / sum of `_stats.csv` | 50,785 / 50,785 |
| Documents (`doc_id`) in the index / in `_stats.csv` | 150 / 150 |
| Documents whose total, text or table counts do not match | none |
| Tickers / tickers without exactly 3 years | 50 / none |
| Chunks per fiscal year | 2019: 16,907 · 2020: 17,120 · 2021: 16,758 |
| Text chunks / table chunks | 39,819 / 10,966 |
| Chunks without a vector / without `company_name` | 0 / 0 |
| Documents with anything embedded during the load (should be 0) | 0 |
| Documents with chunks over 512 tokens | 0 |
| Vector | `dense_vector`, 768 dims, `cosine`, `int8_hnsw` |
| Sections / chunks labeled `Unknown` | 25 / 1,082 |

The package data was also checked before loading: every embedding key recomputed with the current
loader code was found in the cache, in the same order, for all 150 files.

`python -m search_index health` returns `status: ok` (cluster `green`); `stats` returns 50,785
chunks, 150 documents, 50 tickers and 25 sections.

### Index settings (PR #13)

The loader now applies `INDEX_SETTINGS` on every run. After loading: `number_of_replicas: 0`, the
cluster is **green** (it was `yellow` with the 25-company index), and
`index.query.default_field: ["content"]`. With the last one, the query `AAPL` filtered to
`AAPL_2019_10K` (202 chunks) matches 27 chunks instead of all 202.

### Note: rebuild the `index` image after pulling `main`

The first load ran with a stale Docker image: `docker compose run` does not rebuild, and the
`index` image had been built on 2026-10-11, before PR #13. The data loaded correctly (50,785
chunks, all counts matching), but the settings above were **not** applied: the index kept
`number_of_replicas: 1` and no `default_field`. Running `docker compose --profile index build index`
and loading again fixed it, with no re-embedding (all vectors came from the cache). Whoever loads
after a `git pull` should build the image first.

## DB-07: reindex in place

The first load updated the 25-company index to the 50-company package without recreating it:

| Operation | Result |
|---|---|
| Load v5 over the 25-company index | 150 documents written, 0 embedded, 21 documents had old chunks removed (23 chunks in total; consistent with the ETL fixes in PR #26 and #31, which the package README says changed 20 documents plus Illumina) |
| Second load with the rebuilt image | 150 written, 0 embedded, 0 removed; 50,785 |

The purge of a single document (a moved `.jsonl`), the single-document load and `--recreate` were
verified on 2026-10-11 against the previous package (25 companies) and were **not** repeated for v5.

## Search check from the README

`python -m src.load --check "What are Apple's supply chain risks?"` (real model):

```
--- BM25: What are Apple's supply chain risks?
  18.356  FAST_2021_10K_p27_c2  [Item 1 Business, p.27, text]  With the help of third-party resources and global databases...
  18.230  GILD_2021_10K_p21_c2  [Item 1A Risk Factors, p.21, text]  We are also aware of the existence of various suppliers...
  17.296  ENPH_2021_10K_p33_c1  [Item 1A Risk Factors, p.33, text]  Such tariffs could hurt the demand for these products...

--- Vector: What are Apple's supply chain risks?
  0.878  AAPL_2021_10K_p10_c3  [Item 1A Risk Factors, p.10, text]  Many of the Company's operations and facilities...
  0.878  AAPL_2021_10K_p12_c1  [Item 1A Risk Factors, p.12, text]  While the Company relies on its partners to adhere...
  0.877  AAPL_2021_10K_p14_c3  [Item 1A Risk Factors, p.14, text]  The Company depends on the performance of carriers...
```

Without a filter BM25 returns other companies and the vector search finds the right one; with
`--doc AAPL_2019_10K` both return Apple's chunks (BM25 top: `AAPL_2019_10K_p15_c2`, 13.026). That is
why `search/` filters by ticker and fiscal year.

## Observations

Updated with respect to the 2026-10-11 version of this file.

1. **BM25 scoring metadata: fixed** by PR #13 (see Index settings above).
2. **The cluster stayed `yellow`: fixed** by PR #13 (`number_of_replicas: 0`).
3. **`company` as a slug: fixed** by `company_name` (PR #25), present in every chunk as a `keyword`.
   Two tickers carry two official names across years: `FB` (`Facebook, Inc.`, `Meta Platforms, Inc.`)
   and `STX` (two wordings of "Seagate Technology … public limited company").
4. **`_stats.csv` `year_check`:** 142 documents `ok`, 7 `check` (fiscal year ending in the first days
   of January or February: Cadence 2020 and 2021, Dollar Tree 2019 to 2021, Illumina 2020 and 2021;
   the package README explains it) and **1 `not found` (`ATVI_2020_10K`)**, which the package README
   does not mention.
5. **`fuzziness`** was compared on 2026-10-11 with the 25-company index and the old evaluation set
   (top-1 in the expected section 40/75 with `AUTO` against 43/75 with `0`, within noise). It was not
   measured again: PR #36 changed the text BM25 receives, and the evaluation set now has 150
   questions.

Neither the index structure nor the team repo was modified by this verification.
