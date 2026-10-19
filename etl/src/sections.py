"""
Assign a 10-K section ("Item 1A", "Item 7", ...) to every line of a document.

Standard 10-Ks carry numbered headings ("Item 1A. Risk Factors"), required by
SEC Rule 12b-13. Two traps:
  - the table of contents repeats every heading near the start, so its pages
    are ignored. A contents page lists many Items, each followed by its page
    number; a body page can also hold several short sections in a row (Items
    1B to 4, or 10 to 14), but their headings carry no page numbers;
  - some filers don't use numbered headings (Microsoft's investor report,
    Intel's reordered 10-K). For them, known captions are mapped to the Item
    they correspond to; anything else stays "Unknown".

Some filers place the financial statements after the last Item, "Item 16. Form
10-K Summary": after the signature page (Qualcomm, Amgen, Dexcom) or just before
it (Activision). Their first caption there ("Report of Independent Registered
Public Accounting Firm" or "Index to Consolidated Financial Statements")
switches back to Item 8. Nothing but exhibits and the financial statements can
follow Item 16, so the caption is not a line of the Item 15 exhibit list.
"""

import re

from .classify import SIGNATURE_STATEMENT, flatten

# "Item 1A. Risk Factors", "ITEM 7:", "Item 8" alone, or "Item 2 Properties";
# but not a sentence that starts with a reference, like "Item 7 of this Form 10-K".
# The lookahead keeps the Item letter in the number: without it, "Item 1A of this
# report" was read as the heading "Item 1" followed by the capital "A".
ITEM_HEADING = re.compile(r"^\s*(?:ITEM|Item)\s+(\d{1,2}[A-Ca-c]?)(?![A-Ca-c])\s*(?:[.:\-–—]|$|\|\s*[A-Z]|[A-Z])")
# A table of contents lists at least this many distinct Items...
TOC_MIN_ITEMS = 4
# ...and at least this share of its Item lines end with a page number ("Item 3. | Legal Proceedings | 36").
# Measured on the 75 filings: contents pages 68-100%, body pages with short sections 0%.
TOC_NUMBERED_SHARE = 0.5
# A list this long is a table of contents even without page numbers (real ones list 19-22 Items)
TOC_MANY_ITEMS = 15
PAGE_NUMBER_AT_END = re.compile(r"(?:\||\s)\s*\d{1,3}\s*$")

# Captions used without "Item N" by filers that reorder or restyle the 10-K.
# Order matters: the longer, more specific captions go first.
CAPTION_TO_ITEM = [
    (re.compile(r"^QUANTITATIVE AND QUALITATIVE DISCLOSURES? ABOUT MARKET RISK", re.I), "Item 7A"),
    (re.compile(r"^MANAGEMENT.S DISCUSSION AND ANALYSIS", re.I), "Item 7"),
    (re.compile(r"^FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA", re.I), "Item 8"),
    (re.compile(r"^RISK FACTORS$", re.I), "Item 1A"),
    (re.compile(r"^LEGAL PROCEEDINGS$", re.I), "Item 3"),
    (re.compile(r"^PROPERTIES$", re.I), "Item 2"),
    (re.compile(r"^BUSINESS$", re.I), "Item 1"),
]

FINANCIAL_STATEMENTS_START = re.compile(
    r"^(?:REPORT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRMS?|INDEX TO (?:THE )?(?:CONSOLIDATED )?FINANCIAL STATEMENTS)$",
    re.I,
)

UNKNOWN = "Unknown"


def item_label(number: str) -> str:
    return f"Item {number.upper()}"


def is_toc_page(lines: list[str]) -> bool:
    headings = [(m.group(1).upper(), l) for l in lines if (m := ITEM_HEADING.match(l))]
    items = {item for item, _ in headings}
    if len(items) < TOC_MIN_ITEMS:
        return False
    numbered = sum(1 for _, l in headings if PAGE_NUMBER_AT_END.search(l))
    return numbered / len(headings) >= TOC_NUMBERED_SHARE or len(items) >= TOC_MANY_ITEMS


def caption_item(line: str) -> str | None:
    """Map an all-caps caption line to its Item, if it is one we know."""
    text = line.split(" | ")[0].strip()
    if not text.isupper() or len(text) > 90:
        return None
    for pattern, item in CAPTION_TO_ITEM:
        if pattern.match(text):
            return item
    return None


MIN_HEADING_CELL_WORDS = 3  # "ITEM 3 — LEGAL PROCEEDINGS", not a bare "Item 8."
MAX_HEADING_CELL_WORDS = 15
# A heading is a caption: its long words are capitalised. A reference in a sentence is not
# ("| Item 1A. Risk Factors included in this report.")
MIN_LONG_WORD = 4
QUOTE = re.compile(r'[“"]')


def is_caption(text: str) -> bool:
    words = [w.strip(".,;:()\"'’“”") for w in text.split()]
    return all(w[:1].isupper() for w in words if len(w) >= MIN_LONG_WORD and w.isalpha())


def heading_match(line: str) -> re.Match | None:
    """An Item heading at the start of the line, or as the last cell of a line where a
    two-column page put it after the left column's text ("...stock. | ITEM 7A — QUANTITATIVE")."""
    cells = line.split(" | ")
    m = ITEM_HEADING.match(line)
    if m:
        # A heading never quotes: 'Item 1. Business – “Employees and Labor Relations.”' is a
        # reference to a subsection (American Airlines), not the start of Item 1
        return None if QUOTE.search(cells[0]) else m
    last = cells[-1].strip()
    if len(cells) > 1 and MIN_HEADING_CELL_WORDS <= len(last.split()) <= MAX_HEADING_CELL_WORDS and is_caption(last) and not QUOTE.search(last):
        return ITEM_HEADING.match(last)
    return None


def label_lines(pages: list[list[str]]) -> list[list[str]]:
    """For each page, the section of each of its lines. Same shape as `pages`."""
    has_items = any(
        ITEM_HEADING.match(l) for lines in pages if not is_toc_page(lines) for l in lines
    )
    current = UNKNOWN
    signed = False
    labels = []
    for lines in pages:
        toc = is_toc_page(lines)
        page_labels = []
        for line in lines:
            # The statements' own heading starts Item 8 after the signatures or Item 16 (Qualcomm),
            # and in a 10-K without "Item N" headings, where nothing else would (Illumina)
            if (signed or current == "Item 16" or not has_items) and FINANCIAL_STATEMENTS_START.match(
                line.split(" | ")[0].strip()
            ):
                current = "Item 8"
            elif not toc:
                if has_items:
                    m = heading_match(line)
                    if m:
                        current = item_label(m.group(1))
                else:
                    current = caption_item(line) or current
            page_labels.append(current)
        labels.append(page_labels)
        # Pages after the signature page can only hold exhibits or the financial statements
        signed = signed or bool(SIGNATURE_STATEMENT.search(flatten("\n".join(lines))))
    return labels
