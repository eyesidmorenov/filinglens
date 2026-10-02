# Deliverable 2: extraction and chunking (ETL)

Turns the annual-report PDFs in `data/raw/` into clean documents and into chunks ready to be embedded and indexed. Every chunk carries what a citation needs: company, ticker, fiscal year, section and page.

```
data/raw/*.pdf ──► classify ──► extract rows ──► clean ──► sections ──► chunks
                                                   │                      │
                                            data/clean/*.json     data/chunks/*.jsonl
```

## How to run

Everything runs in Docker. From the repository root, with the sample PDFs in `data/raw/` (see `eda/download_sample.py`):

```bash
docker compose --profile etl build etl
docker compose --profile etl run --rm etl                          # process every PDF
docker compose --profile etl run --rm etl python -m src.run_pipeline --limit 3
docker compose --profile etl run --rm etl pytest -q                # tests
```

The container runs once and exits. The first run downloads the BGE tokenizer (about 1 MB) into the shared `hf_models` volume.

A document is skipped only if it is **up to date**: its output was produced by this exact ETL code and these settings. Every output records a fingerprint of the code; after pulling a new version of the ETL, or changing `--scope`, the affected documents are redone automatically. Outputs of a document that is now skipped (scanned, or out of scope) are deleted, so they can't reach the index. `--force` redoes everything anyway.

Options of `python -m src.run_pipeline`:

| Option | Meaning |
| --- | --- |
| `--limit N` | Process only the first N PDFs |
| `--scope 10k` | Default. Keep only the Form 10-K pages; a PDF without a 10-K (Microsoft's investor reports) is skipped |
| `--scope all` | Keep every page of every PDF, investor material included |
| `--force` | Redo documents even if they are up to date |

## Output

| File | Content |
| --- | --- |
| `data/clean/<doc_id>.json` | Contract 1, **Document**: metadata, cleaned text of every page kept, fiscal year end from the cover, ETL fingerprint |
| `data/chunks/<doc_id>.jsonl` | Contract 2, **Chunk**: one JSON object per line |
| `data/chunks/_stats.csv` | One row per document in scope: type, pages kept, fiscal year end and year check, chunks, tables, share of unknown sections |
| `data/clean/_skipped.csv` | Documents skipped in the last run, and why (empty when none) |

Files are written to a temporary name and renamed, so an interrupted run never leaves a half-written file.

A chunk:

```json
{
  "chunk_id": "AAPL_2019_10K_p32_c1",
  "doc_id": "AAPL_2019_10K",
  "text": "Table (Item 8): ...\n| | September 28, 2019 | ... |",
  "section": "Item 8",
  "page": 32,
  "company": "apple-inc",
  "ticker": "AAPL",
  "fiscal_year": 2019,
  "content_type": "table",
  "doc_type": "10-K"
}
```

- `page` is the 1-based page of the PDF where the chunk starts.
- `section` is the 10-K Item ("Item 1A", "Item 7", ...), or `"Unknown"` when it cannot be detected.
- `content_type` and `doc_type` are **proposed** additions to the team contract. They are optional, and a consumer that doesn't know them can ignore them.

## How it works

**Three kinds of PDF.** The sample holds pure 10-Ks (Apple, Tesla), 10-Ks wrapped in investor material (NVIDIA, Intel) and investor-only annual reports without a 10-K (Microsoft). `classify.py` finds the SEC Form 10-K cover and the SIGNATURES page. As decided at the September 28 mentoring, the first iteration works with 10-K filings only: the default scope keeps that page range, which drops investor material and exhibits (for Tesla 2020, 323 of 449 pages), and skips PDFs with no 10-K at all.

**Text by rows, not by lines.** `page.get_text()` puts every number of a financial statement on its own line, and `page.find_tables()` does not detect 10-K tables because they have no ruling lines. `layout.py` rebuilds each page as rows of cells from word coordinates, which keeps every figure under its year. See the spike in `spikes/table_spike.py`.

**Cleaning.** Running headers and footers (repeated at the top or bottom of many pages), page numbers, hyphenated line breaks and whitespace (`clean.py`).

**Sections.** Numbered headings ("Item 1A. Risk Factors") are required by SEC Rule 12b-13. The table of contents is ignored, and so are sentences that merely start with a reference ("Item 7 of this Form 10-K…"). Filers without numbered headings get known captions mapped to Items (`sections.py`).

**Chunks sized in tokens.** Size is measured with the embedding model's own tokenizer (`tokens.py`), so no chunk is silently truncated by BGE (512 tokens). Prose is cut by section, then into chunks that close at about 380 tokens, carry about 50 tokens of the previous chunk, never split a sentence, and never pass a hard cap of 440 tokens. The margin leaves room for the context header the index adds before embedding. Financial tables become their own chunks, rendered as Markdown with their title and column headers; a long table is split by rows within the same cap, repeating its header (`chunk.py`). Only lines that look like a title or a column header are pulled above a table: the end of a prose sentence stays with its paragraph.

**Fiscal year check.** The 10-K cover states "For the fiscal year ended September 28, 2019". That date is stored in the clean document and compared with the year in the file name: `year_check` in `_stats.csv` is `ok`, `check` (a year ending in January or February of the next year, a common retail convention), `mismatch` or `not found`. Fiscal years differ by company: NVIDIA's fiscal 2020 ended on January 26, 2020; Apple's fiscal 2019 ended on September 28, 2019.

## Known limitations

- **Intel 2020 and 2021**: Intel reorders its 10-K and only lists Items in a cross-reference index with printed page numbers, so their chunks have `section: "Unknown"` for now. The text is still searchable.
- **NVIDIA** puts its financial statements in Item 15 (Part IV), as its 10-K states. Filtering financial questions by Item 8 alone would miss them.
- **Images and charts** are not processed yet. The plan is to describe them with Claude; the API key decision is pending.
- **Two-column layouts** in investor material may interleave columns. The default `10k` scope avoids most of them.

## Layout

```
etl/
├── Dockerfile
├── requirements.txt
├── spikes/table_spike.py   throwaway: how to extract financial tables
├── src/
│   ├── models.py           contracts 1 and 2 (pydantic)
│   ├── metadata.py         metadata from the inventory or the file name
│   ├── classify.py         document type, Form 10-K page range, fiscal year end
│   ├── layout.py           page -> rows of cells; table helpers
│   ├── clean.py            cleaning rules
│   ├── extract.py          PDF -> Document
│   ├── sections.py         10-K Items per line
│   ├── tokens.py           token counting with the BGE tokenizer; chunk size budget
│   ├── chunk.py            Document -> Chunks
│   └── run_pipeline.py     command line entry point, fingerprints, stats
└── tests/                  unit tests + checks on the real sample (skipped without PDFs)
```
