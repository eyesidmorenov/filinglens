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

A document is skipped only if it is **up to date**: its output was produced by this exact ETL code and these settings. Every output records a fingerprint of the code; after pulling a new version of the ETL, or changing `--scope`, the affected documents are redone automatically. Outputs of a document that is now skipped (scanned, out of scope, unreadable text or wrong company) are deleted, so they can't reach the index. `--force` redoes everything anyway.

When a company leaves the selection, its PDFs leave `data/raw` but its outputs stay, and the index loads every `.jsonl` in `data/chunks`. A full run (no `--limit`) lists those documents at the end; `--prune` deletes their outputs. Deleting is never automatic: the outputs may come from a shared chunks package and can't be rebuilt without their PDFs.

Options of `python -m src.run_pipeline`:

| Option | Meaning |
| --- | --- |
| `--limit N` | Process only the first N PDFs |
| `--scope 10k` | Default. Keep only the Form 10-K pages; a PDF without a 10-K (Microsoft's investor reports) is skipped |
| `--scope all` | Keep every page of every PDF, investor material included |
| `--force` | Redo documents even if they are up to date |
| `--prune` | Delete the outputs of documents whose PDF is no longer in `data/raw` (full runs only) |

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
  "doc_type": "10-K",
  "company_name": "Apple Inc."
}
```

- `page` is the 1-based page of the PDF where the chunk starts.
- `section` is the 10-K Item ("Item 1A", "Item 7", ...), or `"Unknown"` when it cannot be detected.
- `company` is the S3 folder name ("apple-inc"); `company_name` is the official name on that year's 10-K cover ("Apple Inc."; "Facebook, Inc." in 2019-2020 and "Meta Platforms, Inc." in 2021). Citations and the list of companies the chatbot knows should use `company_name`.
- `content_type`, `doc_type` and `company_name` are **proposed** additions to the team contract. They are optional, and a consumer that doesn't know them can ignore them.

## How it works

**Three kinds of PDF.** The sample holds pure 10-Ks (Apple, Tesla), 10-Ks wrapped in investor material (NVIDIA, Intel) and investor-only annual reports without a 10-K (Microsoft). `classify.py` finds the SEC Form 10-K cover and the signature page. As decided at the September 28 mentoring, the first iteration works with 10-K filings only: the default scope keeps that page range, which drops investor material and exhibits (for Tesla 2020, 323 of 449 pages), and skips PDFs with no 10-K at all. Lessons from the 35 candidate companies (105 PDFs):

- The signature page is recognized by its statement ("Pursuant to the requirements of Section 13 or 15(d)... has duly caused this report to be signed", in the variants filers use), not by the word SIGNATURES, which is also a line of the table of contents (it cut Facebook and IDEXX to a few pages). Only when no variant is found does a SIGNATURES heading outside the table of contents end the 10-K.
- Qualcomm, Amgen, Dexcom, Vertex and Cognizant put their financial statements after the signature page, on pages numbered F-1, F-2... The range is extended over those pages, and their chunks are labeled Item 8.
- When the cover is an image (Activision 2020), the 10-K starts at its table of contents.

**Sanity checks** (`checks.py`). A PDF is skipped, with its reason in `_skipped.csv`, when:

- **Unreadable text**: its fonts have no character map, so the text comes out scrambled ("DVSSFOUMZ" instead of "currently" in AMD 2019). A page is unreadable when less than 20% of its words are known to the tokenizer, and the PDF is skipped when more than 20% of its 10-K pages are. A new copy of the PDF is needed.
- **Wrong company**: the 10-K cover shows neither the ticker nor the company name of the file (`CSX_2020.pdf` holds the 10-K of CSW Industrials). Only a real SEC cover is checked: when the 10-K starts at its table of contents, there is nothing to compare.
- **Duplicate file**: the same PDF is stored under two years (Fortinet 2019 and 2020 are byte-for-byte the same file). Indexing both would answer for one year with the other year's report, and which year is right can't be told from the file, so every copy is skipped.

**The official name comes from the cover, not from a list.** `company.py` reads the registrant's name on each 10-K cover, so adding a company needs no hand-made table. It takes the line above "(Exact name of registrant as specified in its charter)"; on covers laid out as a table (Comcast, United Airlines, which list two registrants) or without that caption (Paychex 2019), the first line or cell shaped like a company name ("..., Inc.", "... Corporation", "... S.A."); and when the cover is an image (Activision 2020), the name in the text that matches the S3 folder. Names printed in capitals ("GILEAD SCIENCES, INC.") take the spelling the filing itself uses ("Gilead Sciences, Inc."), which keeps real capitals such as "IDEXX" or "NVIDIA". Checked on the 150 filings of the 50 companies: it matches the hand-made table of the first 25 in 72 of 75, and the other 3 are "Mondelēz", which is how Mondelez writes its own name.

**Text by rows, not by lines.** `page.get_text()` puts every number of a financial statement on its own line, and `page.find_tables()` does not detect 10-K tables because they have no ruling lines. `layout.py` rebuilds each page as rows of cells from word coordinates, which keeps every figure under its year. See the spike in `spikes/table_spike.py`.

**Cleaning.** Running headers and footers (repeated at the top or bottom of many pages), page numbers and whitespace (`clean.py`). A line that ends in a hyphen is joined to the next one and keeps its hyphen: in 10-Ks those are compound words ("third-party", "COVID-19", "Form 10-K"), not words split by syllable.

**Sections.** Numbered headings ("Item 1A. Risk Factors") are required by SEC Rule 12b-13 (`sections.py`).

- The table of contents is ignored. It is recognized because it lists many Items with their page numbers ("Item 3. | Legal Proceedings | 36"). A body page can also hold several short sections in a row (Items 1B to 4, or 10 to 14), but their headings carry no page numbers, so they count. Before this rule, those headings were dropped in 65 of the 75 filings, and Item 3 Legal Proceedings, for example, was labeled with the previous Item.
- Sentences that merely start with a reference are not headings: "Item 7 of this Form 10-K…", "Item 1A of this report…".
- Financial statements placed after the last Item ("Item 16. Form 10-K Summary"), before or after the signature page (Activision, eBay, IDEXX, Qualcomm, Amgen), are labeled Item 8.
- A 10-K without "Item N" headings in its body (Illumina lists its Items only in a cross-reference index at the end) is labeled by its captions ("QUANTITATIVE AND QUALITATIVE DISCLOSURE ABOUT MARKET RISK" → Item 7A). There, the statements' own heading ("INDEX TO CONSOLIDATED FINANCIAL STATEMENTS", "REPORT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRM") starts Item 8: before this rule, Illumina's financial statements showed as Item 7A (about 470 chunks over its three filings). No other filing of the 50 companies changes.
- Filers without numbered headings get known captions mapped to Items.

**Chunks sized in tokens.** Size is measured with the embedding model's own tokenizer (`tokens.py`), so no chunk is silently truncated by BGE (512 tokens). Prose is cut by section, then into chunks that close at about 380 tokens, carry about 50 tokens of the previous chunk, never split a sentence, and never pass a hard cap of 440 tokens. The margin leaves room for the context header the index adds before embedding. Financial tables become their own chunks, rendered as Markdown with their title and column headers; a long table is split by rows within the same cap, repeating its header (`chunk.py`). Only lines that look like a title or a column header are pulled above a table: the end of a prose sentence stays with its paragraph.

**The sentence that introduces a table is copied into its title.** A table's numbers don't say what they measure: Apple's net sales table is titled only by its column headers, and the sentence above it says "The following table shows net sales by category for 2021, 2020 and 2019". When the last sentence before a table ends with ":" or reads like an introduction ("the following table", "as follows", "the table below"), it goes into the table's title (`Table (Item 7): The following table shows net sales by category...`) and also stays in its paragraph. Measured on 8 revenue questions (Apple, Facebook/Meta, Adobe), the reported total reached the 5 chunks given to the generator in 7 of them, against 5 before; Apple's fiscal 2021 total net sales went from missing to positions 2 and 3. On the 75-question evaluation set, the expected section stays about the same (56 → 55 at rank 1, 72 → 72 in the top 5).

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
│   ├── checks.py           unreadable text and wrong-company checks
│   ├── layout.py           page -> rows of cells; table helpers
│   ├── clean.py            cleaning rules
│   ├── extract.py          PDF -> Document
│   ├── sections.py         10-K Items per line
│   ├── tokens.py           token counting with the BGE tokenizer; chunk size budget
│   ├── chunk.py            Document -> Chunks
│   └── run_pipeline.py     command line entry point, fingerprints, stats
└── tests/                  unit tests + checks on the real sample (skipped without PDFs)
```
