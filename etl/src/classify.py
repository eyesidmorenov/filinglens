"""
Which kind of PDF is this, and where does the Form 10-K live inside it?

The sample showed three kinds:
  10-K           SEC cover on page 1 (Apple, Tesla)
  10-K_wrapped   investor material first, full 10-K inside (NVIDIA, Intel)
  annual_report  investor-only report, no 10-K at all (Microsoft)

The 10-K range runs from the SEC cover page to the SIGNATURES page. Anything
after it is exhibits (for Tesla, hundreds of pages of credit agreements).
"""

import re

COVER = re.compile(
    r"SECURITIES\s+AND\s+EXCHANGE\s+COMMISSION.{0,400}?FORM\s+10-K", re.IGNORECASE | re.DOTALL
)
SIGNATURES = re.compile(r"^\s*SIGNATURES\s*$", re.IGNORECASE | re.MULTILINE)

# The cover sits at the top of its page; a mention deeper in the text is a reference
COVER_WINDOW = 1500


def find_cover(page_texts: list[str]) -> int | None:
    """1-based page of the first SEC Form 10-K cover, or None."""
    for i, text in enumerate(page_texts):
        if COVER.search(text[:COVER_WINDOW]):
            return i + 1
    return None


def find_signatures(page_texts: list[str], start: int) -> int | None:
    """1-based page of the first SIGNATURES heading at or after `start`."""
    for i in range(start - 1, len(page_texts)):
        if SIGNATURES.search(page_texts[i]):
            return i + 1
    return None


def classify(page_texts: list[str]) -> tuple[str, tuple[int, int] | None]:
    """Return (doc_type, (first_page, last_page) of the 10-K or None)."""
    start = find_cover(page_texts)
    if start is None:
        return "annual_report", None
    end = find_signatures(page_texts, start) or len(page_texts)
    doc_type = "10-K" if start == 1 else "10-K_wrapped"
    return doc_type, (start, end)
