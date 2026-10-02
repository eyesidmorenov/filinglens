"""
Contract 2 chunks -> Haystack Documents, and the Elasticsearch mapping.

The generation lane (tenk-answer) reads a Haystack Document as Contract 3:
id = chunk_id, content = text, and section / page / company / fiscal_year in
meta. Every other chunk field (doc_id, ticker, doc_type, content_type) also
travels in meta so search can filter by it, plus section_title, added here.
"""

import json
from pathlib import Path

from haystack import Document

TEXT_FIELDS = ("chunk_id", "text")
KEYWORD_FIELDS = ("doc_id", "section", "section_title", "company", "ticker", "doc_type", "chunk_type")
INTEGER_FIELDS = ("page", "fiscal_year")

# Haystack reserves some names (content_type was a Document field in Haystack 1.x).
# A meta key with a reserved name is stored nested under "meta" in Elasticsearch,
# where filters can't reach it, so it is renamed in the index.
RENAMED_IN_INDEX = {"content_type": "chunk_type"}

# Form 10-K item captions (SEC Form 10-K, Parts I-IV), as filed for fiscal 2019-2021
SECTION_TITLES = {
    "Item 1": "Business",
    "Item 1A": "Risk Factors",
    "Item 1B": "Unresolved Staff Comments",
    "Item 2": "Properties",
    "Item 3": "Legal Proceedings",
    "Item 4": "Mine Safety Disclosures",
    "Item 5": "Market for Registrant's Common Equity, Related Stockholder Matters "
              "and Issuer Purchases of Equity Securities",
    "Item 6": "Selected Financial Data",
    "Item 7": "Management's Discussion and Analysis of Financial Condition and Results of Operations",
    "Item 7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "Item 8": "Financial Statements and Supplementary Data",
    "Item 9": "Changes in and Disagreements with Accountants on Accounting and Financial Disclosure",
    "Item 9A": "Controls and Procedures",
    "Item 9B": "Other Information",
    "Item 9C": "Disclosure Regarding Foreign Jurisdictions that Prevent Inspections",
    "Item 10": "Directors, Executive Officers and Corporate Governance",
    "Item 11": "Executive Compensation",
    "Item 12": "Security Ownership of Certain Beneficial Owners and Management "
               "and Related Stockholder Matters",
    "Item 13": "Certain Relationships and Related Transactions, and Director Independence",
    "Item 14": "Principal Accountant Fees and Services",
    "Item 15": "Exhibits and Financial Statement Schedules",
    "Item 16": "Form 10-K Summary",
}


def read_chunks(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def section_title(section: str) -> str:
    return SECTION_TITLES.get(section, "")


def company_name(slug: str) -> str:
    """'apple-inc' -> 'Apple Inc' (the dataset only has the S3 folder name)."""
    return " ".join(part.capitalize() for part in slug.split("-"))


def context_header(meta: dict) -> str:
    """
    Short header embedded together with the chunk text, so a vector also knows
    whose filing and which section it comes from. Never stored as content:
    citations and excerpts show the chunk text only.
    """
    section = meta.get("section", "")
    title = meta.get("section_title", "")
    where = f"{section} {title}".strip() if section != "Unknown" else ""
    parts = [f"{company_name(meta['company'])} ({meta['ticker']})", f"Fiscal {meta['fiscal_year']}"]
    if where:
        parts.append(where)
    return " | ".join(parts)


def embedding_text(document: Document) -> str:
    """Exactly what the model embeds for a chunk: context header, then the chunk text."""
    return context_header(document.meta) + "\n" + document.content


def chunk_to_document(chunk: dict) -> Document:
    meta = {
        RENAMED_IN_INDEX.get(k, k): v
        for k, v in chunk.items()
        if k not in TEXT_FIELDS
    }
    meta["section_title"] = section_title(meta.get("section", ""))
    reserved = set(meta) & Document._field_names()
    if reserved:
        raise ValueError(f"Chunk fields clash with Haystack reserved names: {sorted(reserved)}")
    return Document(id=chunk["chunk_id"], content=chunk["text"], meta=meta)


def index_mapping(dims: int) -> dict:
    """
    Explicit mapping instead of Haystack's default:
      - content uses the English analyzer, so BM25 matches "risks" with "risk"
      - the vector field has the exact model dimensions
      - filter fields are keywords / integers, never free text
    """
    properties = {
        "content": {"type": "text", "analyzer": "english"},
        "embedding": {"type": "dense_vector", "dims": dims, "index": True, "similarity": "cosine"},
    }
    properties.update({f: {"type": "keyword"} for f in KEYWORD_FIELDS})
    properties.update({f: {"type": "integer"} for f in INTEGER_FIELDS})
    return {
        "properties": properties,
        "dynamic_templates": [
            {"strings": {"path_match": "*", "match_mapping_type": "string", "mapping": {"type": "keyword"}}}
        ],
    }


def mapping_problems(actual: dict, expected: dict) -> list[str]:
    """Differences that would make the index behave differently from what this loader expects."""
    problems = []
    have = actual.get("properties", {})
    for field, spec in expected["properties"].items():
        got = have.get(field)
        if got is None:
            problems.append(f"field '{field}' is missing")
            continue
        for key, value in spec.items():
            if key == "index":
                continue  # dense_vector reports index only when it differs from the default
            if got.get(key) != value:
                problems.append(f"field '{field}': {key} is {got.get(key)!r}, expected {value!r}")
    return problems
