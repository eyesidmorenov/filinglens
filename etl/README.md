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

The container runs once and exits. Documents already on disk are skipped; add `--force` to redo them.

Options of `python -m src.run_pipeline`:

| Option | Meaning |
| --- | --- |
| `--limit N` | Process only the first N PDFs |
| `--scope 10k` | Default. Keep only the Form 10-K pages when the PDF has one |
| `--scope all` | Keep every page, investor material included |
| `--force` | Redo documents already processed |

## Output

| File | Content |
| --- | --- |
| `data/clean/<doc_id>.json` | Contract 1, **Document**: metadata plus the cleaned text of every page kept |
| `data/chunks/<doc_id>.jsonl` | Contract 2, **Chunk**: one JSON object per line |
| `data/chunks/_stats.csv` | One row per document: type, pages kept, chunks, tables, share of unknown sections |
| `data/clean/_skipped.csv` | Documents that could not be processed and why |

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

**Three kinds of PDF.** The sample holds pure 10-Ks (Apple, Tesla), 10-Ks wrapped in investor material (NVIDIA, Intel) and investor-only annual reports without a 10-K (Microsoft). `classify.py` finds the SEC Form 10-K cover and the SIGNATURES page. With the default scope only that range is kept, which drops investor material and exhibits (for Tesla 2020, 323 of 449 pages).

**Text by rows, not by lines.** `page.get_text()` puts every number of a financial statement on its own line, and `page.find_tables()` does not detect 10-K tables because they have no ruling lines. `layout.py` rebuilds each page as rows of cells from word coordinates, which keeps every figure under its year. See the spike in `spikes/table_spike.py`.

**Cleaning.** Running headers and footers (repeated at the top or bottom of many pages), page numbers, hyphenated line breaks and whitespace (`clean.py`).

**Sections.** Numbered headings ("Item 1A. Risk Factors") are required by SEC Rule 12b-13. The table of contents is ignored. Filers without numbered headings get known captions mapped to Items (`sections.py`).

**Chunks.** Prose is cut by section, then into windows of about 300 words with 45 words of overlap, without splitting sentences, which stays below BGE's 512-token limit. Financial tables become their own chunks, rendered as Markdown with their column headers (`chunk.py`).

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
│   ├── classify.py         document type and Form 10-K page range
│   ├── layout.py           page -> rows of cells; table helpers
│   ├── clean.py            cleaning rules
│   ├── extract.py          PDF -> Document
│   ├── sections.py         10-K Items per line
│   ├── chunk.py            Document -> Chunks
│   └── run_pipeline.py     command line entry point
└── tests/                  unit tests + checks on the real sample (skipped without PDFs)
```
