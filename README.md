# FilingLens AI

**Financial Advisor Chatbot for NASDAQ companies**

An assistant that answers questions about NASDAQ-listed companies by reading their annual filings, and always says where each answer came from.

Final project for the **ML Developer Career** program at [Anyone AI](https://anyoneai.com). Team 3.

[English](README.md) · [Español](README.es.md)

---

## The problem

Every publicly traded company files an annual report called a **10-K**: 100 to 300 pages covering its business, risks, strategy and financial statements. It is the most reliable document that exists about a company, and also one of the hardest to read.

Comparing three companies means opening 600 pages of PDF and searching by hand.

**FilingLens reads that and answers in seconds.**

## The product rule

> Every answer comes with its source: company, fiscal year, section and page.

In finance a number without backing is useless, and a made-up figure is worse than "I don't know". This rule shapes the prompt, shapes the interface, and defines how we measure whether the system works.

**This is not an investment advisor.** It does not recommend buying or selling. It reports what companies state in their official filings, nothing more.

---

## Architecture

The system has two flows that run independently.

**Indexing, once.** Documents are pulled from S3, text is extracted and cleaned, split into chunks by section, embedded, and stored in the index.

```
S3 → PyMuPDF → cleaning → chunking → embeddings → Elasticsearch
```

**Querying, on every question.** The question comes in through the chat UI, the company and year are detected, the index is searched by keyword and by meaning at the same time, both result lists are fused, and a language model writes the answer with its citations.

```
Chainlit → FastAPI → Haystack (BM25 + vectors → RRF) → Claude → answer with sources
```

## Stack

| Piece | Tool | Why |
| --- | --- | --- |
| Index | Elasticsearch | Stores text and vectors in a single service, free, runs in a container |
| Orchestration | Haystack | Document-focused framework, ships RRF fusion out of the box |
| Embeddings | BGE local | No API key, no quota, everyone runs exactly the same thing |
| Generation | Claude (Anthropic) | Access already available, no risk of running out of credits |
| API | FastAPI | |
| Interface | Chainlit | Pure Python, no JavaScript needed |
| Containers | Docker Compose | Required deliverable |

**Elasticsearch and Haystack are not alternatives, they are different pieces.** Elasticsearch *executes* the search: it scans the index and returns matches. Haystack *directs* it: splits documents, generates embeddings, queries twice, fuses the lists and builds the prompt.

| Question | Elasticsearch | Haystack |
| --- | --- | --- |
| Who splits the PDFs into chunks? | No | Yes |
| Who generates the embeddings? | No | Yes |
| Who fuses both searches with RRF? | No | Yes |
| Who passes context to Claude? | No | Yes |
| Who stores chunks and returns them? | Yes | No |

---

## The dataset

Annual reports and 10-K filings from NASDAQ-listed companies, hosted on S3 by Anyone AI.

| Measure | Value |
| --- | --- |
| Documents | 9,855 PDFs |
| Total size | 29.8 GB |
| Average size | 3.1 MB per document |
| Companies | 2,429 |
| Year range | 2015 to 2022, density between 2018 and 2021 |

### Findings that shaped the scope

**Metadata lives in the filename.** The path `nasdaq_annual_reports/apple-inc/NASDAQ_AAPL_2019.pdf` contains company, exchange, ticker and year. No need to open the PDF to extract them.

**The dataset ends in 2021.** There are no documents from 2023 onward, and 2022 holds only 160 files against 2,237 for 2019. That is why the project scope is **2019, 2020 and 2021**.

**There are two document types, not one.** Some files are the SEC Form 10-K, with numbered Item sections. Others are the shareholder Annual Report, which has no such structure. Across the working sample, 79% are 10-K filings.

If someone asks about a year outside the range, the bot says so instead of staying silent or making something up.

---

## Scope

**In scope:** 25 recognizable NASDAQ companies, three fiscal years, 10-K filings in English only, hybrid search, answers citing company, year, section and page, a chat interface, an API, full containerization, and an evaluation set to measure quality.

**Out of scope:** the full 2,429-company dataset, live news search, authentication, charts, financial tables as structured data, multi-company comparisons in a single answer, arithmetic over retrieved figures, and any form of investment recommendation.

### What kind of questions it answers

| Category | Example |
| --- | --- |
| Natural fit | What are the main risk factors NVIDIA identifies? |
| Needs work | What was Apple's revenue in fiscal year 2021? |
| Out of scope | Compare NVIDIA and AMD on margins |

The third row gets declined gracefully. **A bot that knows its limits is more convincing than one that improvises.**

---

## Repository layout

```
filinglens/
├── eda/            Dataset exploration and analysis
├── etl/            Text extraction and chunking
├── index/          Elasticsearch, embeddings, loading
├── search/         Retrieval pipeline and evaluation
├── generation/     Prompt and Claude integration
├── api/            FastAPI
├── ui/             Chainlit
└── data/           Documents and intermediate output (not tracked)
```

Each folder maps to a deliverable and has an owner. They are created as each lane starts.

---

## Getting started

```bash
git clone https://github.com/eyesidmorenov/filinglens.git
cd filinglens
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r eda/requirements.txt
```

### Credentials

```bash
cp eda/.env.example eda/.env
```

Open `eda/.env` and paste the AWS keys provided in the course brief.

> **Keys never enter the repository.** Not in code, not in a notebook, not in commit history. The `.gitignore` already excludes `.env`. Verify before your first commit with `git check-ignore -v eda/.env`.

### Running the EDA

```bash
python eda/explore_s3.py          # lists the bucket, downloads nothing
python eda/download_sample.py     # downloads the working sample
python eda/characterize.py        # measures the documents
```

The download script is **deterministic**: it always fetches exactly the same files, regardless of who runs it. That way the whole team works from an identical sample and results are comparable.

---

## Data contracts

Each piece of the system hands off to the next in a fixed shape. That is what lets six lanes move in parallel without waiting on each other: whoever needs something another lane is still building works against mock data in the right shape until the real thing lands.

**Document**, between download and extraction:

```json
{
  "doc_id": "AAPL_2019_10K",
  "company": "apple-inc",
  "ticker": "AAPL",
  "fiscal_year": 2019,
  "exchange": "NASDAQ",
  "s3_key": "nasdaq_annual_reports/apple-inc/NASDAQ_AAPL_2019.pdf",
  "local_path": "data/raw/AAPL_2019.pdf",
  "n_pages": 96
}
```

**Chunk**, between chunking and indexing:

```json
{
  "chunk_id": "AAPL_2019_10K_p42_c3",
  "doc_id": "AAPL_2019_10K",
  "text": "...",
  "section": "Item 7",
  "page": 42,
  "company": "apple-inc",
  "ticker": "AAPL",
  "fiscal_year": 2019
}
```

**API response**, between backend and frontend:

```json
{
  "answer": "...",
  "sources": [
    { "company": "apple-inc", "fiscal_year": 2019, "section": "Item 7", "page": 42, "excerpt": "..." }
  ],
  "latency_ms": 1840
}
```

Changing a contract gets announced to the team first, because someone on the other side is building against that shape.

---

## How we work

- **Everyone on `main`.** Lanes do not overlap, so conflicts are rare
- **Each person in their own folder**
- **No data in the repository.** PDFs come from running the download script
- **`git pull` before you start** avoids most of the mess
- **Commits with context:** `type(lane): what you did`

### Set your identity

Inside the project folder, so your commits show up under your name:

```bash
git config user.name "Your Name"
git config user.email "you@example.com"
```

No `--global`, so it only applies to this repository. Commit history is the record of who contributed what.

---

## Deliverables

| # | Deliverable | Folder |
| --- | --- | --- |
| 1 | Exploratory dataset analysis | `eda/` |
| 2 | Preprocessing scripts | `etl/` |
| 3 | Database storage scripts | `index/` |
| 4 | Question, search and answer system | `search/` and `generation/` |
| 5 | API | `api/` |
| 6 | ChatGPT-style interface | `ui/` |
| 7 | Present results and demo | everyone |
| 8 | Full Docker containerization | root |

---

## Team

Six members, each owning one lane. See the team agreements document for who covers what.

## License

Academic project. The dataset belongs to Anyone AI, and the underlying documents are public filings submitted to the SEC by the issuing companies.
