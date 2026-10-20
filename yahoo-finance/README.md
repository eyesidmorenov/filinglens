# Yahoo Finance coverage check

> 🇪🇸 Versión en español: [README.es.md](README.es.md)

**Research spike, not part of the chatbot yet.** The 10-K filings in the course dataset stop
at fiscal 2021. This folder measures what Yahoo Finance could add after that, for each of our
25 companies, so the team can decide with data whether and how to use it.

## The idea

| Question about | Source | Citation |
| --- | --- | --- |
| Fiscal 2019 to 2021 | 10-K (Elasticsearch index) | Company, fiscal year, section, page |
| Fiscal 2022 onwards | Yahoo Finance (proposal) | "Yahoo Finance, fetched on <date>" |

The rules do not change: always cite, never recommend an investment, say "I don't know" when
there is no data. That is why this check never reads analyst ratings or price targets.

## What it does

For each company in [`tickers.csv`](tickers.csv) it reads, through the `yfinance` library:

- the annual **income statement**: Total Revenue, Gross Profit, Operating Income, Net Income
- the annual **balance sheet**: Total Assets, Total Debt, Stockholders Equity
- the annual **cash flow statement**: Operating Cash Flow, Free Cash Flow

and writes, in `data/` (never committed):

| File | Content |
| --- | --- |
| `data/yahoo/coverage.csv` | One row per company: status, fiscal years found, years after 2021, missing figures |
| `data/yahoo/snapshots/<TICKER>.json` | The key figures per fiscal year, with the source and the date they were fetched |

The snapshots let a demo run without calling Yahoo live. Each one also stores the
`currency` of the figures (taken from Yahoo's `financialCurrency`): the amounts are raw, so
Apple's revenue `416161000000` means USD 416.2 billion.

**Fiscal year.** A figure's fiscal year is the calendar year of its period end, the same rule as
the 10-K file names: NVIDIA's fiscal 2023 ends in January 2023. Yahoo moves period ends to the
end of the month (Apple shows 2025-09-30 for September 27), so the dates in `fiscal_year_end` are
approximate; the year is not.

## Run it

From the repository root:

```bash
docker compose --profile yahoo build yahoo
docker compose --profile yahoo run --rm yahoo                                  # the 25 companies, ~1 minute
docker compose --profile yahoo run --rm yahoo python -m src.coverage --limit 3  # quick test
docker compose --profile yahoo run --rm yahoo pytest -q                         # tests, no network needed
```

It needs internet access. If Yahoo returns nothing for every company, the run ends with a
warning: `yfinance` turns a blocked or offline request into empty tables, not an error.

## Known cases

| 10-K ticker | Yahoo ticker | Why |
| --- | --- | --- |
| FB | META | The ticker changed from FB to META in 2022 |
| ATVI | ATVI | Acquired by Microsoft in 2023: probably no recent data (`no_data`) |

## Limits to keep in mind

- `yfinance` is **not an official Yahoo API**: it can break or be blocked without notice. For the
  demo, use the saved snapshots, not a live call.
- Yahoo usually shows **about four** fiscal years of annual statements. The coverage table
  says exactly which ones each company has.
- Yahoo's line items are **not always the 10-K's**: Apple reports "net sales", Yahoo shows
  "Total Revenue". Any answer must say which source the figure comes from.
- There is no page to cite: the citation becomes source + fetch date.

## Decisions for the team (after the first run)

1. Is the coverage good enough for the 25 companies?
2. Which figures do we use: only the income statement, or the three statements?
3. How does the chatbot choose the source: by the fiscal year in the question?
4. Live call or saved snapshots for the demo?
