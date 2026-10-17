"""
The company's official name, as printed on its 10-K cover.

The S3 folder only gives a slug ("the-kraft-heinz-company"); the cover gives the
legal name ("The Kraft Heinz Company"), which is what citations should show and
what people type ("Kraft Heinz"). Reading it from every filing means a new
company needs no hand-made list: the name changes with the company (Facebook,
Inc. -> Meta Platforms, Inc. in 2021).

Where the name is, in order:
  1. Above "(Exact name of registrant as specified in its charter)": the
     standard cover.
  2. The first line or table cell of the cover that looks like a company name:
     covers laid out as a table (Comcast, United Airlines, which list two
     registrants and give the parent first) or without that caption (Paychex).
  3. The document text, by the S3 slug, when the cover can't be read (an image,
     as Activision 2020).
Names printed in capitals ("GILEAD SCIENCES, INC.") take the spelling the
filing uses in its own text ("Gilead Sciences, Inc."), which keeps real
capitals such as "IDEXX" or "NVIDIA".
"""

import re
from collections import Counter

EXACT_NAME = re.compile(
    r"\(?\s*exact\s+name\s+of\s+(?:the\s+)?registrants?\s+as\s+specified\s+in\s+(?:its|their)\s+charters?",
    re.IGNORECASE,
)
# A legal-entity ending: "Inc.", "Corporation", "Company", "S.A.", "plc"...
LEGAL_SUFFIX = re.compile(
    r"(?:\b(?:Inc|Incorporated|Corp|Corporation|Company|Co|Ltd|Limited|LLC|L\.P|plc|PLC|N\.V|S\.A|AG|SE|"
    r"Holdings|Group)\.?)\s*$",
    re.IGNORECASE,
)
MAX_NAME_WORDS = 8
COVER_LINES = 40  # the registrant block sits at the top of the cover


def looks_like_name(text: str) -> bool:
    words = text.split()
    return 1 <= len(words) <= MAX_NAME_WORDS and bool(LEGAL_SUFFIX.search(text)) and not any(c.isdigit() for c in text)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.split("|") if c.strip()]


def _from_caption(lines: list[str]) -> str | None:
    """Rule 1: the name sits right above (or before, on the same line) the caption."""
    for i, line in enumerate(lines):
        m = EXACT_NAME.search(line)
        if not m:
            continue
        before = line[:m.start()].strip(" |")
        candidates = [before] if before else [lines[j].strip(" |") for j in range(i - 1, max(i - 4, -1), -1)]
        for candidate in candidates:
            for cell in reversed(_cells(candidate) or [candidate]):
                if looks_like_name(cell):
                    return cell
    return None


def _from_cover_block(lines: list[str]) -> str | None:
    """Rule 2: the first line or table cell at the top of the cover shaped like a company name."""
    for line in lines[:COVER_LINES]:
        for cell in _cells(line):
            if looks_like_name(cell):
                return cell
    return None


def _from_slug(slug: str, text: str) -> str | None:
    """Rule 3: the most frequent company-shaped phrase in the text that starts with the slug's words."""
    words = [w for w in slug.split("-") if w not in {"inc", "corp", "corporation", "co", "the", "ltd", "plc"}]
    if not words:
        return None
    pattern = re.compile(
        r"\b(?:The\s+)?" + r"[\s,]+".join(re.escape(w) for w in words) + r"[\w\s,.&'’]{0,40}?"
        r"\b(?:Inc|Incorporated|Corporation|Company|Ltd|Limited|plc|S\.A|N\.V)\.?",
        re.IGNORECASE,
    )
    found = Counter(m.group(0).strip() for m in pattern.finditer(text))
    return found.most_common(1)[0][0] if found else None


def _words(text: str) -> list[str]:
    """Letters and digits, lower case: "CADENCE DESIGN SYSTEMS INC" -> cadence, design, systems, inc."""
    return re.findall(r"[a-z0-9]+", text.casefold())


def _usual_spelling(name: str, text: str) -> str:
    """A name in capitals takes the most frequent spelling of the same name in the text."""
    if any(c.islower() for c in name):
        return name
    words = _words(name)
    if not words:
        return name
    # The same words in order, with any punctuation or spacing between them
    pattern = re.compile(r"\b" + r"[\W_]*".join(re.escape(w) for w in words) + r"\b\.?", re.IGNORECASE)
    variants = Counter(
        m.group(0)
        for m in pattern.finditer(text)
        if m.group(0)[0].isupper() and any(c.islower() for c in m.group(0))
    )
    return " ".join(variants.most_common(1)[0][0].split()) if variants else name


def official_name(cover_text: str, document_text: str, slug: str) -> str | None:
    """The registrant's name from the cover, spelled as the filing writes it; None if not found."""
    lines = cover_text.split("\n")
    name = _from_caption(lines) or _from_cover_block(lines) or _from_slug(slug, document_text)
    if not name:
        return None
    # Straight apostrophe, the one people type: "O'Reilly", not "O’Reilly"
    return _usual_spelling(name, document_text).replace("’", "'")
