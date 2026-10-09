"""
Sanity checks on a PDF before its text reaches the index.

Unreadable text. Some PDFs embed their fonts without a character map, so the
extracted text comes out as shifted or scrambled letters ("DVSSFOUMZ" instead
of "currently" in AMD 2019). To the embedding model those pages are noise. A
page counts as unreadable when less than 20% of its words are words the
tokenizer knows. Real pages score far higher: prose above 70%, and even a
table of drug names scores 28% (Amgen 2021). Broken pages score 0-10%.

Wrong company. The file name says which company a PDF belongs to, but the
bucket can be wrong: CSX_2020.pdf holds the 10-K of CSW Industrials. Since
April 2019 every 10-K cover lists its trading symbol; older covers at least
carry the company name.
"""

import re

from .classify import flatten
from .tokens import vocabulary

WORD = re.compile(r"[A-Za-z]{3,}")
MIN_WORDS = 40                  # pages with fewer words (charts, numbers) are not judged
UNREADABLE_PAGE_SCORE = 0.2     # share of known words below which a page is unreadable
MAX_UNREADABLE_SHARE = 0.2      # share of unreadable pages above which the document is skipped

# Words in the company folder name that do not identify the company
GENERIC_WORDS = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "plc", "the"}


def known_word_share(text: str) -> float | None:
    """Share of the page's words found in the tokenizer vocabulary, or None if too few words."""
    words = WORD.findall(text)
    if len(words) < MIN_WORDS:
        return None
    known = vocabulary()
    return sum(w.lower() in known for w in words) / len(words)


def unreadable_pages(page_texts: list[str]) -> tuple[int, int]:
    """(unreadable pages, pages with enough words to judge)."""
    scores = [s for s in map(known_word_share, page_texts) if s is not None]
    return sum(s < UNREADABLE_PAGE_SCORE for s in scores), len(scores)


def company_key(company: str) -> str | None:
    """'csx-corp' -> 'csx', 'oreilly-automotive-inc' -> 'oreilly'; None when unknown."""
    words = [w for w in company.lower().split("-") if w and w not in GENERIC_WORDS]
    return words[0] if words and company != "unknown" else None


def names_company(cover_text: str, ticker: str, company: str) -> bool | None:
    """
    Does the cover belong to this company? True when it shows the ticker or the
    company name, False when it shows neither, None when there is nothing to
    compare with (no ticker on an old cover and no company name in the inventory).
    """
    flat = flatten(cover_text)
    if re.search(rf"(?<![A-Za-z]){re.escape(ticker)}(?![A-Za-z])", flat):
        return True
    key = company_key(company)
    if key is None:
        return None
    # "Amazon.com" and "O'Reilly" are written "amazoncom" and "oreilly" in the folder names
    squeezed = re.sub(r"[.'’]", "", flat.lower())
    return re.search(rf"\b{re.escape(key)}\b", squeezed) is not None
