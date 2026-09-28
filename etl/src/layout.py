"""
Rebuild a page as rows of text from word coordinates.

Why not page.get_text()? In financial statements it puts every number on its
own line, so a figure loses its row and its year. Why not page.find_tables()?
10-K tables have no ruling lines and it only finds one-row fragments. The table
spike (etl/spikes/table_spike.py) showed that grouping words by their vertical
position keeps every number in its row and column, on all three document kinds.

Each row is a list of cells: words closer than CELL_GAP points stay in one cell.
"""

import re

import pymupdf

Y_TOLERANCE = 4.0  # points; words whose vertical centres differ less share a row
CELL_GAP = 12.0  # points; a wider horizontal gap starts a new cell

NUMBER = re.compile(r"^\(?-?\$?\d[\d,]*(\.\d+)?\)?%?$|^[—–-]$")


def page_rows(page: pymupdf.Page) -> list[list[str]]:
    """Rows of cells for one page, top to bottom, left to right."""
    words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, word_no)
    # Currency signs sit in their own column and would glue cells together
    words = [w for w in words if w[4] not in ("$", "€")]
    words.sort(key=lambda w: (w[1] + w[3]) / 2)

    clusters: list[list] = []
    for w in words:
        centre = (w[1] + w[3]) / 2
        if clusters and abs(centre - clusters[-1][0]) <= Y_TOLERANCE:
            clusters[-1][1].append(w)
        else:
            clusters.append([centre, [w]])

    rows = []
    for _, row in clusters:
        row.sort(key=lambda w: w[0])
        cells, current, prev = [], [], None
        for w in row:
            if prev is not None and w[0] - prev[2] > CELL_GAP:
                cells.append(" ".join(current))
                current = []
            current.append(w[4])
            prev = w
        cells.append(" ".join(current))
        # Dot leaders ("Revenue........") are layout, not content
        cells = [re.sub(r"\.{3,}", "", c).strip() for c in cells]
        cells = [c for c in cells if c]
        if cells:
            rows.append(cells)
    return rows


def is_table_row(cells: list[str]) -> bool:
    """A label followed by two or more numeric cells, e.g. 'Net income | 55,256 | 59,531'."""
    numeric = sum(1 for c in cells[1:] if NUMBER.match(c.replace(" ", "")))
    return len(cells) >= 3 and numeric >= 2


YEAR = re.compile(r"^(19|20)\d{2}$")


def is_year_header(cells: list[str]) -> bool:
    """'Year Ended June 30, | 2020 | 2019 | 2018': looks numeric but is a header."""
    values = [c for c in cells if NUMBER.match(c.replace(" ", ""))]
    return len(values) >= 2 and all(YEAR.match(v) for v in values)


def rows_to_markdown(rows: list[list[str]], header_rows: int = 1) -> str:
    """
    Render rows as a Markdown table. Rows shorter than the table are padded on
    the left, because column headers ("2019 | 2018") have no label cell.
    Several header rows ("September 28, | ..." over "2019 | ...") are merged.
    """
    width = max(len(r) for r in rows)
    # A one-cell row is a label ("Revenue:") and belongs in the first column;
    # a shorter multi-cell row is a header or number row missing its label
    padded = [
        r + [""] * (width - 1) if len(r) == 1 else [""] * (width - len(r)) + r
        for r in rows
    ]
    header_rows = max(1, min(header_rows, len(padded)))
    header = [" ".join(parts).strip() for parts in zip(*padded[:header_rows])]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * width]
    for r in padded[header_rows:]:
        lines.append("| " + " | ".join(c.replace("|", "/") for c in r) + " |")
    return "\n".join(lines)
