"""
Assign a 10-K section ("Item 1A", "Item 7", ...) to every line of a document.

Standard 10-Ks carry numbered headings ("Item 1A. Risk Factors"), required by
SEC Rule 12b-13. Two traps:
  - the table of contents repeats every heading near the start, so pages that
    list many Items are ignored;
  - some filers don't use numbered headings (Microsoft's investor report,
    Intel's reordered 10-K). For them, known captions are mapped to the Item
    they correspond to; anything else stays "Unknown".
"""

import re

ITEM_HEADING = re.compile(r"^\s*ITEM\s+(\d{1,2}[A-C]?)\s*(?:[.:\-–—]|\s|$)", re.IGNORECASE)
# A page listing this many distinct Items is a table of contents or an index
TOC_MIN_ITEMS = 4

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

UNKNOWN = "Unknown"


def item_label(number: str) -> str:
    return f"Item {number.upper()}"


def is_toc_page(lines: list[str]) -> bool:
    items = {m.group(1).upper() for l in lines if (m := ITEM_HEADING.match(l))}
    return len(items) >= TOC_MIN_ITEMS


def caption_item(line: str) -> str | None:
    """Map an all-caps caption line to its Item, if it is one we know."""
    text = line.split(" | ")[0].strip()
    if not text.isupper() or len(text) > 90:
        return None
    for pattern, item in CAPTION_TO_ITEM:
        if pattern.match(text):
            return item
    return None


def label_lines(pages: list[list[str]]) -> list[list[str]]:
    """For each page, the section of each of its lines. Same shape as `pages`."""
    has_items = any(
        ITEM_HEADING.match(l) for lines in pages if not is_toc_page(lines) for l in lines
    )
    current = UNKNOWN
    labels = []
    for lines in pages:
        toc = is_toc_page(lines)
        page_labels = []
        for line in lines:
            if not toc:
                if has_items:
                    m = ITEM_HEADING.match(line)
                    if m:
                        current = item_label(m.group(1))
                else:
                    current = caption_item(line) or current
            page_labels.append(current)
        labels.append(page_labels)
    return labels
