"""
Which kind of PDF is this, and where does the Form 10-K live inside it?

The sample showed three kinds:
  10-K           SEC cover on page 1 (Apple, Tesla)
  10-K_wrapped   investor material first, full 10-K inside (NVIDIA, Intel)
  annual_report  investor-only report, no 10-K at all (Microsoft)

The 10-K range runs from the SEC cover page to the signature page. Anything
after it is exhibits (for Tesla, hundreds of pages of credit agreements),
except the financial statements: Qualcomm, Amgen, Dexcom, Vertex and
Cognizant place them after the signature page, on pages numbered F-1, F-2...,
so the range is extended over those pages.

The signature page is found by its fixed statement ("Pursuant to the
requirements of Section 13 or 15(d) ... the registrant has duly caused this
report to be signed"), not by the word SIGNATURES: that word is also a line of
the table of contents, which cut Facebook and IDEXX to a few pages.
"""

import re
from datetime import date, datetime

SEC = re.compile(r"SECURITIES\s+AND\s+EXCHANGE\s+COMMISSION", re.IGNORECASE)
FORM_10K = re.compile(r"FORM\s+10-K\b", re.IGNORECASE)
ANNUAL_REPORT = re.compile(r"ANNUAL\s+REPORT\s+PURSUANT\s+TO\s+SECTION\s+13", re.IGNORECASE)
WASHINGTON = re.compile(r"Washington,?\s+D\.?\s*C\.?", re.IGNORECASE)
SIGNATURE_STATEMENT = re.compile(
    r"Pursuant\s+to\s+the\s+requirements\s+of\s+Section\s+13\s+or\s+15\s*\(\s*d\s*\)"
    r"|duly\s+caused\s+this\s+(?:annual\s+)?report",
    re.IGNORECASE,
)
ITEM = re.compile(r"\bItem\s+(1A|1B|1|2|3|4|5|6|7A|7|8|9A|9B|9|10|11|12|13|14|15)\b", re.IGNORECASE)
F_PAGE_NUMBER = re.compile(r"F\s*-\s*\d{1,3}")

# The cover sits at the top of its page; a mention deeper in the text is a reference
COVER_WINDOW = 2000
# A 10-K table of contents lists most Items; investor material never does
MIN_CONTENTS_ITEMS = 10
# Pages without an F-number tolerated between the signatures and the F-pages
# (Amgen inserts two exhibits), or among the F-pages themselves (Vertex)
MAX_F_GAP = 3


def flatten(text: str) -> str:
    """One line, single spaces, table cells merged back into the sentence."""
    return " ".join(text.replace(" | ", " ").split())


def is_cover(text: str) -> bool:
    """
    The SEC cover: commission name, form name, and either 'Annual report pursuant
    to Section 13' or the commission's address. The commission name and form name
    alone are not enough: exhibit lists cite filings 'with the Securities and
    Exchange Commission ... on Form 10-K' (Fiserv 2021). The address covers
    Intel 2021, whose cover text is interleaved with its corporate directory.
    """
    top = flatten(text)[:COVER_WINDOW]
    return bool(SEC.search(top) and FORM_10K.search(top) and (ANNUAL_REPORT.search(top) or WASHINGTON.search(top)))


def is_contents(text: str) -> bool:
    """
    The 10-K table of contents, for PDFs whose cover is an image (Activision 2020).
    Not a cross-reference index: Intel's maps each Item to pages of its annual
    report and sits at the end of the PDF.
    """
    top = flatten(text)[:COVER_WINDOW]
    items = {m.upper() for m in ITEM.findall(top)}
    lower = top.lower()
    return len(items) >= MIN_CONTENTS_ITEMS and "risk factors" in lower and "cross-reference" not in lower


def find_cover(page_texts: list[str]) -> int | None:
    """1-based page where the Form 10-K starts: its SEC cover, or else its table of contents."""
    for check in (is_cover, is_contents):
        for i, text in enumerate(page_texts):
            if check(text):
                return i + 1
    return None


def find_signatures(page_texts: list[str], start: int) -> int | None:
    """1-based page of the signature statement at or after `start`."""
    for i in range(start - 1, len(page_texts)):
        if SIGNATURE_STATEMENT.search(flatten(page_texts[i])):
            return i + 1
    return None


def is_f_page(text: str) -> bool:
    """A page numbered F-1, F-2... at its top or bottom: the financial statements.
    The number can be a cell of the footer row ("Cognizant | F-1 | December 31, 2021 Form 10-K")."""
    lines = [l for l in text.split("\n") if l.strip()]
    cells = [c.strip() for l in lines[:2] + lines[-2:] for c in l.split(" | ")]
    return any(F_PAGE_NUMBER.fullmatch(c) for c in cells)


def financial_pages_end(page_texts: list[str], signatures: int) -> int:
    """Last F-page right after the signature page, or the signature page if there are none."""
    end, gap = signatures, 0
    for i in range(signatures, len(page_texts)):
        if is_f_page(page_texts[i]):
            end, gap = i + 1, 0
        else:
            gap += 1
            if gap > MAX_F_GAP:
                break
    return end


FISCAL_YEAR_END = re.compile(
    r"for\s+the\s+fiscal\s+year\s+ended:?\s+([A-Z][a-z]+)\s+(\d{1,2})\s*,?\s*(\d{4})", re.IGNORECASE
)


def fiscal_year_end(cover_text: str) -> date | None:
    """'For the fiscal year ended September 28, 2019' on the 10-K cover -> date(2019, 9, 28)."""
    m = FISCAL_YEAR_END.search(flatten(cover_text))
    if not m:
        return None
    month, day, year = m.groups()
    try:
        return datetime.strptime(f"{month[:3]} {day} {year}", "%b %d %Y").date()
    except ValueError:
        return None


def year_check(file_year: int, end: date | None) -> str:
    """
    Compare the year in the file name with the fiscal year end on the cover.
    'ok' when they match; 'check' when the year ends in January or February of
    the next year (retailers often name that fiscal year after the previous
    one); 'mismatch' otherwise; 'not found' when the cover has no date.
    """
    if end is None:
        return "not found"
    if end.year == file_year:
        return "ok"
    if end.year == file_year + 1 and end.month <= 2:
        return "check"
    return "mismatch"


def classify(page_texts: list[str]) -> tuple[str, tuple[int, int] | None]:
    """Return (doc_type, (first_page, last_page) of the 10-K or None)."""
    start = find_cover(page_texts)
    if start is None:
        return "annual_report", None
    signatures = find_signatures(page_texts, start)
    end = financial_pages_end(page_texts, signatures) if signatures else len(page_texts)
    doc_type = "10-K" if start == 1 else "10-K_wrapped"
    return doc_type, (start, end)
