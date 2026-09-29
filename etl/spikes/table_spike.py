"""
Spike DA-04: do financial tables survive PDF extraction with their columns aligned?

Throwaway code. It answers one question and writes a report; nothing here is
imported by the pipeline.

For one document of each type found in the sample (pure 10-K, 10-K wrapped in
investor material, investor-only annual report) it locates the income statement
page and extracts it three ways:

  1. page.get_text()             plain text, what we'd get by doing nothing special
  2. page.get_text("words")      words with coordinates, rebuilt into rows
  3. page.find_tables()          PyMuPDF table detection, exported as Markdown

Usage:
    python etl/spikes/table_spike.py
Output:
    data/spikes/table_spike_report.md
"""

import re
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "spikes"

# One document per type found in the sample analysis
DOCS = {
    "AAPL_2019.pdf": "A: pure 10-K",
    "NVDA_2020.pdf": "B: 10-K wrapped in investor material",
    "MSFT_2020.pdf": "C: investor-only annual report",
}

# Titles companies use for the income statement
TITLE = re.compile(
    r"CONSOLIDATED STATEMENTS? OF (OPERATIONS|INCOME)|^\s*INCOME STATEMENTS\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# A real statement page has these rows; a table of contents does not
MUST_HAVE = [re.compile(r"net income", re.I), re.compile(r"(total )?net sales|revenue", re.I)]
# Summary tables elsewhere in the filing that share the same rows
SKIP = re.compile(r"SELECTED FINANCIAL DATA", re.IGNORECASE)


def find_income_statement(doc: pymupdf.Document) -> int | None:
    """Return the 0-based index of the first page that looks like the income statement."""
    for i, page in enumerate(doc):
        text = page.get_text()
        if not TITLE.search(text) or SKIP.search(text):
            continue
        if not all(p.search(text) for p in MUST_HAVE):
            continue
        # Statement pages are dense with numbers; TOC and notes pages are not
        numbers = re.findall(r"\(?\$?\d{1,3}(?:,\d{3})+\)?", text)
        if len(numbers) >= 20:
            return i
    return None


def words_to_rows(page: pymupdf.Page, y_tolerance: float = 4.0) -> list[str]:
    """Group words that share a line into rows and mark column gaps with ' | '."""
    words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, word_no)
    # Currency signs sit in their own column and glue neighbouring cells together
    words = [w for w in words if w[4] != "$"]
    words.sort(key=lambda w: (w[1] + w[3]) / 2)

    # Cluster by vertical centre: a word joins the row if its centre is close enough
    rows: list[list] = []
    for w in words:
        centre = (w[1] + w[3]) / 2
        if rows and abs(centre - rows[-1][0]) <= y_tolerance:
            rows[-1][1].append(w)
        else:
            rows.append([centre, [w]])

    out = []
    for _, row in rows:
        row.sort(key=lambda w: w[0])
        parts = [row[0][4].strip(".")]
        for prev, w in zip(row, row[1:]):
            parts.append(" | " if w[0] - prev[2] > 12 else " ")
            parts.append(w[4].strip("."))
        out.append(re.sub(r"\s+", " ", "".join(parts)).strip())
    return out


def rows_with(lines: list[str], label: str) -> list[str]:
    return [l for l in lines if re.search(label, l, re.I)]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    report = ["# Spike DA-04: financial tables\n"]
    summary = []

    for name, kind in DOCS.items():
        doc = pymupdf.open(RAW / name)
        idx = find_income_statement(doc)
        report.append(f"\n## {name} ({kind})\n")
        if idx is None:
            report.append("Income statement page not found.\n")
            summary.append((name, kind, None, "not found", "-", "-"))
            continue
        page = doc[idx]
        report.append(f"Income statement found on PDF page **{idx + 1}**.\n")

        # 1. Plain text
        plain = [l.strip() for l in page.get_text().splitlines() if l.strip()]
        report.append("\n### 1. `get_text()` (plain)\nRows mentioning net income / net sales:\n```")
        report.extend(rows_with(plain, r"net income|net sales|revenue")[:6])
        report.append("```\nFirst 25 lines as extracted:\n```")
        report.extend(plain[:25])
        report.append("```")

        # 2. Words rebuilt into rows
        rows = words_to_rows(page)
        report.append("\n### 2. `get_text('words')` rebuilt into rows\n```")
        report.extend(rows[:30])
        report.append("```")
        net = rows_with(rows, r"^net income\b")
        aligned = bool(net) and len(net[0].split(" | ")) >= 4

        # 3. Table detection
        tables = page.find_tables()
        report.append(f"\n### 3. `find_tables()`: {len(tables.tables)} table(s) detected\n")
        md = ""
        if tables.tables:
            biggest = max(tables.tables, key=lambda t: t.row_count * t.col_count)
            md = biggest.to_markdown()
            report.append(f"Biggest table: {biggest.row_count} rows x {biggest.col_count} columns\n")
            report.append(md)
        else:
            report.append("No table detected on this page.\n")

        summary.append((
            name, kind, idx + 1,
            "numbers lost their row" if not rows_with(plain, r"net income \d") else "ok",
            "aligned: " + net[0] if aligned else "not aligned",
            f"{len(tables.tables)} fragment(s), biggest {biggest.row_count}x{biggest.col_count}"
            if tables.tables else "no table",
        ))

    report.insert(1, "\n| Document | Type | Page | 1. get_text | 2. words -> rows | 3. find_tables |\n|---|---|---|---|---|---|")
    for i, s in enumerate(summary):
        report.insert(2 + i, "| " + " | ".join(str(x) for x in s) + " |")

    path = OUT / "table_spike_report.md"
    path.write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report[:2 + len(summary)]))
    print(f"\nFull report: {path}")


if __name__ == "__main__":
    main()
