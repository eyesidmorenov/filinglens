"""
Text cleaning rules. Each rule is a small function with its own test.

The cleaning works on lines (one line per rebuilt row) so that page headers and
footers can be recognised by repetition across pages.
"""

import re
from collections import Counter

PAGE_NUMBER = re.compile(r"^(page\s+)?\d{1,3}$|^[ivxlc]{1,6}$", re.IGNORECASE)
HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
# A line counts as a running header/footer if it repeats on this share of pages
REPEAT_SHARE = 0.3
MIN_PAGES_FOR_REPEATS = 5
# Headers and footers live at the edges of a page; lines in the middle are
# content, even when they repeat (e.g. "Basic | 5.82 | 5.11" in every statement)
EDGE_LINES = 2


def edges(lines: list[str]) -> list[str]:
    content = [l for l in lines if l.strip()]
    return content[:EDGE_LINES] + content[-EDGE_LINES:]


def normalize_for_repeat(line: str) -> str:
    """Page numbers change between pages; compare lines without their digits."""
    return re.sub(r"\d+", "#", line.strip().lower())


def find_repeated_lines(pages: list[list[str]]) -> set[str]:
    """Normalized lines that appear on many pages: running headers and footers."""
    if len(pages) < MIN_PAGES_FOR_REPEATS:
        return set()
    counts = Counter()
    for lines in pages:
        counts.update({normalize_for_repeat(l) for l in edges(lines)})
    threshold = max(3, int(len(pages) * REPEAT_SHARE))
    return {line for line, n in counts.items() if n >= threshold}


def is_page_number(line: str) -> bool:
    return bool(PAGE_NUMBER.match(line.strip()))


def join_hyphenated(text: str) -> str:
    """
    'long-\\nterm' -> 'long-term': a line that ends in a hyphen continues on the next one.

    The hyphen stays. In the 105 PDFs of the 35 candidate companies, about 2,900
    lines end in a hyphen, and they are compound words ("third-party", "non-GAAP",
    "COVID-19", "Form 10-K"), not words split by syllable. Dropping the hyphen
    produced "thirdparty" and "10K", which keyword search can't match.
    """
    return HYPHEN_BREAK.sub(r"\1-\2", text)


def normalize_whitespace(text: str) -> str:
    text = text.replace(" ", " ").replace("​", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_pages(pages: list[list[str]]) -> list[str]:
    """Remove headers, footers and page numbers; return one clean text per page."""
    repeated = find_repeated_lines(pages)
    out = []
    for lines in pages:
        edge = set(edges(lines))
        kept = [
            l for l in lines
            if l.strip()
            and not is_page_number(l)
            and not (l in edge and normalize_for_repeat(l) in repeated)
        ]
        out.append(normalize_whitespace(join_hyphenated("\n".join(kept))))
    return out
