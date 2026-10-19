"""
Rebuild a page as rows of text from word coordinates.

Why not page.get_text()? In financial statements it puts every number on its
own line, so a figure loses its row and its year. Why not page.find_tables()?
10-K tables have no ruling lines and it only finds one-row fragments. The table
spike (etl/spikes/table_spike.py) showed that grouping words by their vertical
position keeps every number in its row and column, on all three document kinds.

Each row is a list of cells: words closer than CELL_GAP points stay in one cell.

Some filers print the 10-K body in two columns (Nasdaq, Xcel Energy, Biogen).
Read row by row, a line of the left column would be followed by the line of the
right column at the same height, and a heading in the right column ("ITEM 7A")
would land in the middle of a line. On those pages the left column is read first,
then the right one; rows that cross the middle (a full-width title) stay in place.
"""

import re

import pymupdf

Y_TOLERANCE = 4.0  # points; words whose vertical centres differ less share a row
CELL_GAP = 12.0  # points; a wider horizontal gap starts a new cell

NUMBER = re.compile(r"^\(?-?\$?\d[\d,]*(\.\d+)?\)?%?$|^[—–-]$")

# Two columns: the blank strip between them is near the middle of the page, and
# many rows hold prose on both sides (a table's right side holds numbers instead)
GUTTER_ZONE = (0.35, 0.65)  # share of the page width where the gutter is looked for
# A gutter is a blank strip at least this wide that almost no row crosses. The spaces
# between words of one-column text are ~3 points wide and move from line to line.
GUTTER_WIDTH = 8.0  # points
MAX_CROSSING_SHARE = 0.1  # rows allowed to cross it (full-width titles)
MIN_PROSE_WORDS = 4
MAX_NUMERIC_SHARE = 0.2
MIN_TWO_COLUMN_ROWS = 8  # rows with prose on both sides of the gutter
MIN_TWO_COLUMN_SHARE = 0.3  # ... as a share of the page's rows

Word = tuple  # (x0, y0, x1, y1, text, block, line, word_no), as pymupdf returns it


def clusters(words: list[Word]) -> list[list[Word]]:
    """Group words into rows by their vertical centre, top to bottom."""
    rows: list[list] = []
    for w in sorted(words, key=lambda w: (w[1] + w[3]) / 2):
        centre = (w[1] + w[3]) / 2
        if rows and abs(centre - rows[-1][0]) <= Y_TOLERANCE:
            rows[-1][1].append(w)
        else:
            rows.append([centre, [w]])
    return [row for _, row in rows]


def row_cells(row: list[Word]) -> list[str]:
    """One row's words, left to right, split into cells at wide gaps."""
    cells, current, prev = [], [], None
    for w in sorted(row, key=lambda w: w[0]):
        if prev is not None and w[0] - prev[2] > CELL_GAP:
            cells.append(" ".join(current))
            current = []
        current.append(w[4])
        prev = w
    cells.append(" ".join(current))
    # Dot leaders ("Revenue........") are layout, not content
    cells = [re.sub(r"\.{3,}", "", c).strip() for c in cells]
    return [c for c in cells if c]


def is_column_line(words: list[Word]) -> bool:
    """A line of a text column: one continuous cell of mostly words. A table's side has
    several cells, or numbers and dashes ("— %"), so it never counts."""
    texts = [w[4] for w in words]
    if len(texts) < MIN_PROSE_WORDS or len(row_cells(words)) != 1:
        return False
    not_words = sum(1 for t in texts if not any(ch.isalpha() for ch in t) or any(ch.isdigit() for ch in t))
    return not_words / len(texts) < MAX_NUMERIC_SHARE


def two_column_gutter(words: list[Word], width: float) -> float | None:
    """The x of the blank strip between two prose columns, or None for a one-column page."""
    if not words or width <= 0:
        return None
    rows = clusters(words)
    half = GUTTER_WIDTH / 2

    def rows_crossing(x: float) -> int:
        return sum(1 for row in rows if any(w[0] < x + half and w[2] > x - half for w in row))

    # The strip in the middle zone crossed by the fewest rows (the centre of the widest such run)
    lo, hi = int(width * GUTTER_ZONE[0]), int(width * GUTTER_ZONE[1])
    crossings = {x: rows_crossing(x) for x in range(lo, hi + 1, 2)}
    fewest = min(crossings.values())
    if fewest > MAX_CROSSING_SHARE * len(rows):
        return None
    candidates = [x for x, n in crossings.items() if n == fewest]
    gutter = candidates[len(candidates) // 2]

    # Each side needs its own lines of text (not always at the same height: a column can
    # hold a table next to text in the other one). A full-width table never qualifies:
    # the side after the gutter holds its numbers, not text.
    left = sum(1 for row in rows if is_column_line([w for w in row if w[2] <= gutter]))
    right = sum(1 for row in rows if is_column_line([w for w in row if w[0] >= gutter]))
    if min(left, right) >= MIN_TWO_COLUMN_ROWS and min(left, right) >= MIN_TWO_COLUMN_SHARE * len(rows):
        return gutter
    return None


def column_rows(words: list[Word], gutter: float) -> list[list[str]]:
    """Rows of a two-column page: each band of two-column rows left column first, then
    right; a row that crosses the gutter (a full-width title) ends the band in place."""
    rows, left, right = [], [], []

    def flush():
        rows.extend(row_cells(r) for r in clusters(left))
        rows.extend(row_cells(r) for r in clusters(right))
        left.clear()
        right.clear()

    for row in clusters(words):
        if any(w[0] < gutter < w[2] for w in row):
            flush()
            rows.append(row_cells(row))
        else:
            left.extend(w for w in row if w[2] <= gutter)
            right.extend(w for w in row if w[0] >= gutter)
    flush()
    return [r for r in rows if r]


def page_rows(page: pymupdf.Page) -> list[list[str]]:
    """Rows of cells for one page, top to bottom, left to right (one column after the other on two-column pages)."""
    words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, word_no)
    # Currency signs sit in their own column and would glue cells together
    words = [w for w in words if w[4] not in ("$", "€")]
    gutter = two_column_gutter(words, page.rect.width)
    if gutter is not None:
        return column_rows(words, gutter)
    return [cells for row in clusters(words) if (cells := row_cells(row))]


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
