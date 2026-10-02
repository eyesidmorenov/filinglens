"""
PDF -> Document (contract 1).

Steps: read every page as rows (layout.page_rows), classify the document,
keep the pages in scope, and clean them. Table rows keep their cells joined by
" | " so the chunker can rebuild the table later.

Scope (decided at the 2026-09-28 mentoring: first iteration is 10-K only):
  "10k"  keep only the Form 10-K pages; a PDF without a 10-K is skipped
  "all"  keep every page of every PDF, investor material included
"""

from pathlib import Path

import pymupdf

from .classify import classify, fiscal_year_end
from .clean import clean_pages
from .layout import page_rows
from .models import Document, Page

# Average characters per page below this means a scanned PDF with no text layer
MIN_CHARS_PER_PAGE = 100


class ScannedDocumentError(Exception):
    pass


class OutOfScopeError(Exception):
    """The document has no Form 10-K and the scope is 10-K only."""


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

    doc_type, form_range = classify(["\n".join(lines) for lines in raw_pages])

    if scope == "10k":
        if not form_range:
            raise OutOfScopeError(f"{pdf.name}: {doc_type}, no Form 10-K inside")
        first, last = form_range
    else:
        first, last = 1, n_pages
    selected = raw_pages[first - 1:last]
    cleaned = clean_pages(selected)

    cover = "\n".join(raw_pages[form_range[0] - 1]) if form_range else ""

    return Document(
        **meta,
        n_pages=n_pages,
        doc_type=doc_type,
        form_10k_pages=form_range,
        fiscal_year_end=fiscal_year_end(cover),
        etl_fingerprint=fingerprint,
        pages=[
            Page(page=first + i, text=text)
            for i, text in enumerate(cleaned)
            if text
        ],
    )
