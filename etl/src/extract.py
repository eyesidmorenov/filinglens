"""
PDF -> Document (contract 1).

Steps: read every page as rows (layout.page_rows), classify the document,
keep the pages in scope, and clean them. Table rows keep their cells joined by
" | " so the chunker can rebuild the table later.

Scope (pending the mentor's decision on investor material):
  "10k"  keep only the Form 10-K pages when the PDF has one; investor-only
         reports are kept whole (option 3 in the team write-up)
  "all"  keep every page
"""

from pathlib import Path

import pymupdf

from .classify import classify
from .clean import clean_pages
from .layout import page_rows
from .models import Document, Page

# Average characters per page below this means a scanned PDF with no text layer
MIN_CHARS_PER_PAGE = 100


class ScannedDocumentError(Exception):
    pass


def read_rows(pdf: Path) -> tuple[int, list[list[str]]]:
    """(number of pages, one list of ' | '-joined lines per page)."""
    with pymupdf.open(pdf) as doc:
        pages = [[" | ".join(cells) for cells in page_rows(page)] for page in doc]
    return len(pages), pages


def extract_document(pdf: Path, meta: dict, scope: str = "10k") -> Document:
    n_pages, raw_pages = read_rows(pdf)

    chars = sum(len(l) for lines in raw_pages for l in lines)
    if chars / max(n_pages, 1) < MIN_CHARS_PER_PAGE:
        raise ScannedDocumentError(f"{pdf.name}: {chars // max(n_pages, 1)} chars per page")

    doc_type, form_range = classify(["\n".join(lines) for lines in raw_pages])

    if scope == "10k" and form_range:
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
        pages=[
            Page(page=first + i, text=text)
            for i, text in enumerate(cleaned)
            if text
        ],
    )
