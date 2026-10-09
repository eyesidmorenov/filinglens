"""
PDF -> Document (contract 1).

Steps: read every page as rows (layout.page_rows), classify the document,
check that its text is readable and that it belongs to the company in the file
name (checks.py), keep the pages in scope, and clean them. Table rows keep
their cells joined by " | " so the chunker can rebuild the table later.

Scope (decided at the 2026-09-28 mentoring: first iteration is 10-K only):
  "10k"  keep only the Form 10-K pages; a PDF without a 10-K is skipped
  "all"  keep every page of every PDF, investor material included
"""

from pathlib import Path

import pymupdf

from .checks import MAX_UNREADABLE_SHARE, unreadable_pages, wrong_company
from .classify import classify, fiscal_year_end
from .clean import clean_pages
from .layout import page_rows
from .models import Document, Page

# Average characters per page below this means a scanned PDF with no text layer
MIN_CHARS_PER_PAGE = 100


class SkippedDocument(Exception):
    """The document is left out of the outputs; `reason` goes to _skipped.csv."""

    reason = "skipped"


class ScannedDocumentError(SkippedDocument):
    reason = "scanned"


class OutOfScopeError(SkippedDocument):
    """The document has no Form 10-K and the scope is 10-K only."""

    reason = "out of scope"


class UnreadableTextError(SkippedDocument):
    """The PDF's fonts give garbled text; a new copy of the PDF is needed."""

    reason = "unreadable text"


class WrongCompanyError(SkippedDocument):
    """The 10-K cover belongs to another company than the file name says."""

    reason = "wrong company"


def read_rows(pdf: Path) -> tuple[int, list[list[str]]]:
    """(number of pages, one list of ' | '-joined lines per page)."""
    with pymupdf.open(pdf) as doc:
        pages = [[" | ".join(cells) for cells in page_rows(page)] for page in doc]
    return len(pages), pages


def extract_document(pdf: Path, meta: dict, scope: str = "10k", fingerprint: str | None = None) -> Document:
    n_pages, raw_pages = read_rows(pdf)

    chars = sum(len(l) for lines in raw_pages for l in lines)
    if chars / max(n_pages, 1) < MIN_CHARS_PER_PAGE:
        raise ScannedDocumentError(f"{pdf.name}: {chars // max(n_pages, 1)} chars per page")

    page_texts = ["\n".join(lines) for lines in raw_pages]
    doc_type, form_range = classify(page_texts)

    # Judge only the 10-K pages: a wrapper can be garbled while its 10-K is fine (Autodesk 2019)
    judged = page_texts[form_range[0] - 1:form_range[1]] if form_range else page_texts
    bad, total = unreadable_pages(judged)
    if total and bad / total > MAX_UNREADABLE_SHARE:
        raise UnreadableTextError(f"{pdf.name}: {bad} of {total} pages are garbled (font without character map)")

    if form_range and wrong_company(page_texts, form_range[0], meta["ticker"], meta["company"]):
        raise WrongCompanyError(f"{pdf.name}: the 10-K cover names neither {meta['ticker']} nor {meta['company']}")

    if scope == "10k":
        if not form_range:
            raise OutOfScopeError(f"{pdf.name}: {doc_type}, no Form 10-K inside")
        first, last = form_range
    else:
        first, last = 1, n_pages
    selected = raw_pages[first - 1:last]
    cleaned = clean_pages(selected)

    return Document(
        **meta,
        n_pages=n_pages,
        doc_type=doc_type,
        form_10k_pages=form_range,
        fiscal_year_end=fiscal_year_end(page_texts[form_range[0] - 1]) if form_range else None,
        etl_fingerprint=fingerprint,
        pages=[
            Page(page=first + i, text=text)
            for i, text in enumerate(cleaned)
            if text
        ],
    )
