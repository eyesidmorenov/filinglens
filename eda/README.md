# Deliverable 1: dataset EDA

*English · [Español](README.es.md)*

Measures the dataset before building anything on top of it. It doesn't clean or transform anything: that is deliverable 2.

## Setup

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate      # on Windows: .venv\Scripts\activate
pip install -r eda/requirements.txt
cp eda/.env.example eda/.env
```

Open `eda/.env` and paste the read-only keys from the brief.

## How to run it

The scripts measure and save to disk. The notebook only reads what they saved.

| Step | Command | What it does | What it leaves |
| --- | --- | --- | --- |
| 1 | `python eda/explore_s3.py` | Lists the whole bucket, downloads nothing. Parses every path, detects hash suffixes and duplicates | `data/eda/bucket_inventory.csv`, `data/eda/bucket_unparsed.csv` |
| 2 | `python eda/download_sample.py` | Downloads the working sample: 5 companies, 2019 to 2021. Deterministic | PDFs in `data/raw/`, `data/raw/inventario.csv` |
| 3 | `python eda/characterize.py` | Opens each PDF and measures pages, text, Item sections, tables | `data/eda/caracterizacion.csv`, `data/eda/caracterizacion.json` |
| 4 | Open `eda/eda_filinglens.ipynb` and run all | Plots and documents the findings | |

`download_sample.py --check` checks what is in the bucket without downloading.

### From the sample to 100 companies: three batches

The companies were added in three batches. Each batch follows the same two steps: the EDA picks
**candidates by rules**, from the bucket inventory, and the ETL checks have the **final word**,
because only opening each PDF shows whether it can be used.

**The rules**

| Rule | Why |
| --- | --- |
| Fiscal 2019, 2020 and 2021 in the bucket | The scope of the project: the dataset ends in 2021 |
| A US company listed on NASDAQ | Foreign companies usually file a 20-F, and the ETL keeps only Form 10-K |
| Batches 1 and 2: well-known Nasdaq-100 names, in priority order | Recognizable companies make the product easy to try and to explain |
| Batch 3: the largest by market value today (Yahoo Finance) | The Nasdaq-100 list was used up: of its names with the three years, only Atlassian was left, and it files a 20-F |
| Not tried in an earlier batch, not already in the index | Each batch adds new companies only |
| More candidates than needed (35 for 25, 70 for 50) | About 70% pass the ETL checks |

**The batches**

| Batch | Candidates | Kept | List | Status |
| --- | --- | --- | --- | --- |
| 1 | 35 | 25 | `eda/companies.csv` | In the index |
| 2 | 35 | 25 | `eda/companies_batch2.csv` | In the index |
| 3 | 70 | 50 | `eda/companies_batch3.csv` | Selected; it enters the index for the final demo (100 companies) |

The index today holds 50 companies, 150 filings and 50,785 chunks.

**Why a candidate was left out.** In batch 3, every candidate has its result in the `result` column:

| Reason | Companies |
| --- | --- |
| The ETL skipped at least one year: unreadable text, a scanned PDF or no 10-K | 14 |
| The financial statements are not in the 10-K text | 4 |
| The file of a year holds another fiscal year's 10-K (Axon 2019 is fiscal 2018; Freedom Holding 2021 is fiscal 2022) | 2 |

In batches 1 and 2, 10 candidates of each are not in the index: they failed an ETL check, or 25
companies had already passed. Documented examples: Microsoft (investor reports without a 10-K),
AMD 2019 (unreadable text), CSX 2020 (the file holds the 10-K of CSW Industrials) and Fortinet
(the same file under 2019 and 2020). Each ETL run lists the skipped documents and their reason in
`data/clean/_skipped.csv`.

**What the batches taught us.** Every batch brought a format the previous ones did not have:
tables without ruling lines, two-column pages, financial statements on F-pages after the
signatures, and companies that name their fiscal year differently. That is why the EDA proposes
and the ETL decides. Adding the companies themselves needs no code change: the API and the Yahoo
Finance snapshots read the list of companies from the index.

| Command | What it does |
| --- | --- |
| `python eda/select_companies.py` | Batches 1 and 2. Reads `bucket_inventory.csv` (no S3 calls) and keeps 35 well-known companies with fiscal 2019, 2020 and 2021. Writes `eda/companies.csv` |
| `docker compose --profile yahoo run --rm -v ./eda:/app/eda yahoo python eda/select_by_market_cap.py` | Batch 3. Among the bucket companies with the three years, the largest by market value. Writes `eda/companies_batch3.csv` |
| `python eda/download_sample.py --companies eda/companies.csv` | Downloads the PDFs of a batch instead of the 5-company sample |

The output file names (`inventario.csv`, `caracterizacion.*`) and their columns stay as they are: the ETL and the notebook read them.

## What we found

| Finding | Data |
| --- | --- |
| The metadata is in the file name | 9,852 of 9,855 PDFs follow `EXCHANGE_TICKER_YEAR.pdf`, 45 with a hash suffix |
| The dataset ends in 2021 | It goes from 2003 to 2022, almost 80% between 2018 and 2021 |
| There are two types of documents | 10-K with Item sections, and Annual Reports without them |
| The ticker is the key, not the folder name | 11 tickers with duplicate documents due to errors or name changes |

The detail and the charts are in the notebook.

## Important

`.env` is in `.gitignore`. The keys can never enter the repository: not in the code, not in a notebook, not in the history.
