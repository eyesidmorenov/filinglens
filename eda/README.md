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

### From the sample to 25 companies

| Command | What it does |
| --- | --- |
| `python eda/select_companies.py` | Reads `bucket_inventory.csv` (no S3 calls) and keeps 35 well-known companies with fiscal 2019, 2020 and 2021. Writes `eda/companies.csv` |
| `python eda/download_sample.py --companies eda/companies.csv` | Downloads those companies instead of the 5-company sample |

It picks 35 on purpose: the ETL drops the filings without a 10-K, and the project keeps the first 25 that pass.

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
