# Yahoo Finance coverage and snapshots

> 🇪🇸 Versión en español: [README.es.md](README.es.md)

The 10-K filings in the course dataset stop at fiscal 2021. This folder reads what Yahoo
Finance has after that for the 50 companies in the index, and saves it as **snapshots**: one
JSON file per company that the API reads when a question asks about fiscal 2022 or later.

## The idea (agreed on 2026-10-20)

| Question about | Source | Citation |
| --- | --- | --- |
| Fiscal 2019 to 2021 | 10-K (Elasticsearch index) | Company, fiscal year, section, page |
| Fiscal 2022 onwards | Yahoo Finance snapshot, passed to Claude as one more chunk | "Yahoo Finance · fetched on <date>" (`page: 0`) |
| A year with no snapshot | none | "I don't have that year" |

- **The chat never calls Yahoo live.** The snapshots are the cache: asking about Apple 2023 a
  hundred times calls Yahoo zero times, and the demo works even if Yahoo is down.
- **Yahoo does not go into Elasticsearch.** A 10-K has hundreds of pages and must be searched;
  a snapshot has a few figures per company and year, so the API opens the right file directly.
- The rules do not change: always cite, never recommend an investment, say "I don't know" when
  there is no data. That is why this check never reads analyst ratings or price targets.

## What it does

For each company **in the index** it reads, through the `yfinance` library:

- the annual **income statement**: Total Revenue, Gross Profit, Operating Income, Net Income
- the annual **balance sheet**: Total Assets, Total Debt, Stockholders Equity
- the annual **cash flow statement**: Operating Cash Flow, Free Cash Flow

**The list of companies scales on its own.** It comes from the ETL output in `data/chunks/`:
`_stats.csv` (one row per 10-K, with its fiscal year and the date it ended) and the first chunk
of each filing (S3 folder and official name). Adding companies to the index adds them here,
with no file to edit. [`overrides.csv`](overrides.csv) only holds the exceptions: a different
Yahoo ticker (FB is META) and notes on acquired companies.

and writes, in `data/` (never committed):

| File | Content |
| --- | --- |
| `data/yahoo/coverage.csv` | One row per company: status, fiscal years found, years after 2021, missing figures |
| `data/yahoo/snapshots/<TICKER>.json` | The key figures per fiscal year, their `currency`, the date each fiscal year ended, the source and the date they were fetched |

A company with no data (`no_data`) gets no snapshot, so the API answers "I don't have that year".

The amounts are raw, in the snapshot's `currency` (Yahoo's `financialCurrency`): Apple's revenue
`416161000000` means USD 416.2 billion.

## Fiscal years follow the 10-K

Yahoo labels each year with the date it ended, and companies name their fiscal years
differently. The snapshot uses the same fiscal year as the company's 10-K, so "Dollar Tree
2023" means the same in Yahoo and in the index:

| Rule (`fiscal_year_rule`) | The fiscal year is | Example |
| --- | --- | --- |
| `end_year` (47 companies) | the calendar year of the end date | NVIDIA: ended 2021-01-31 → fiscal 2021 |
| `most_months` (Cadence, Dollar Tree, Illumina) | the calendar year where most of the year falls | Dollar Tree: ended 2020-02-01 → fiscal 2019 |

**Each company's rule is chosen from its own 10-Ks**: the plain rule (`end_year`) if it gives
the fiscal year of every filing, else `most_months`. A company whose 10-Ks fit neither is left
out and reported, so the API answers "I don't have that year" instead of showing another
year's figures. `--check-fiscal-years` lists the rules chosen, without calling Yahoo: today
47 companies use `end_year` and 3 use `most_months`.

Yahoo moves period ends to the end of the month (Apple shows 2025-09-30 for September 27), so
the dates in `fiscal_year_end` are approximate. The fiscal year is not: both rules give the same
year for the real date and for the end of its month.

## Run it

From the repository root:

```bash
docker compose --profile yahoo build yahoo
docker compose --profile yahoo run --rm yahoo python -m src.coverage --check-fiscal-years  # no network
docker compose --profile yahoo run --rm yahoo                                              # the 50 companies, ~2 minutes
docker compose --profile yahoo run --rm yahoo python -m src.coverage --limit 3              # quick test
docker compose --profile yahoo run --rm yahoo pytest -q                                     # tests, no network
```

The coverage check needs internet access. If Yahoo returns nothing for every company, the run
ends with a warning: `yfinance` turns a blocked or offline request into empty tables, not an error.

## First run with the 50 companies (2026-10-20)

- **46 of 50 companies have data**: four fiscal years each, 2022-2025, or 2023-2026 for the
  companies whose fiscal year ends in the first half of the calendar year (NVIDIA, Lam Research,
  Autodesk, KLA, Electronic Arts, Paychex, Cintas, Logitech, NetApp, Okta, Seagate, Western Digital).
- **4 have no data**, as expected: they were acquired and no longer trade.

| 10-K ticker | Yahoo ticker | Why |
| --- | --- | --- |
| FB | META | The ticker changed from FB to META in 2022 |
| ATVI | ATVI | Acquired by Microsoft in 2023: `no_data` |
| CERN | CERN | Acquired by Oracle in 2022: `no_data` |
| SPLK | SPLK | Acquired by Cisco in 2024: `no_data` |
| ANSS | ANSS | Acquired by Synopsys in 2025: `no_data` |

## Limits to keep in mind

- `yfinance` is **not an official Yahoo API**: it can break or be blocked without notice. That
  is why the chat reads the saved snapshots and never calls Yahoo.
- Yahoo shows **about four** fiscal years of annual statements. The coverage table says
  exactly which ones each company has.
- Yahoo's figures can be **restated**: after Dollar Tree sold Family Dollar (2025), Yahoo shows
  its past revenue without that business (fiscal 2022: about $15.4 billion, against about $28
  billion in its 10-K). An answer from Yahoo must say where the figure comes from.
- Yahoo's line items are **not always the 10-K's**: Apple reports "net sales", Yahoo shows
  "Total Revenue".
- There is no page to cite: the citation becomes source + fetch date.
