"""Filtered BM25 + vector retrieval, fused with Haystack's RRF joiner."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from haystack import Document

from . import config
from .index_contract import make_document_store

TICKER = re.compile(r"^[A-Z0-9.\-]{1,12}$")
CONTRACT3_META = ("section", "page", "company", "fiscal_year")

# "in fiscal 2019", "for fiscal year 2020", "FY2021", "2019"
YEAR_MENTION = re.compile(r"\b(?:(?:in|for|during)\s+)?(?:fiscal(?:\s+year)?\s+|FY\s?)?(?:19|20)\d{2}\b", re.IGNORECASE)
# Where the official name stops being the company's own name ("Apple Inc.", "Fastenal Company")
LEGAL_ENDINGS = {
    "inc", "incorporated", "corporation", "corp", "company", "co", "limited", "ltd", "plc",
    "public", "holdings", "group", "s.a", "sa", "n.v", "nv", "llc", "lp",
}


def clean_question(question: str) -> str:
    value = " ".join(question.split())
    if not value:
        raise ValueError("question must not be empty")
    return value


def company_name_words(company_name: str) -> list[str]:
    """The words that name the company: 'The Kraft Heinz Company' -> ['kraft', 'heinz']."""
    plain = unicodedata.normalize("NFKD", company_name).encode("ascii", "ignore").decode()
    words = [w.strip(",.").lower() for w in plain.replace("’", "'").split()]
    if words and words[0] == "the":
        words = words[1:]
    name = []
    for word in words:
        if not word or word in LEGAL_ENDINGS:
            break
        name.append(word)
    return name


def keyword_query(question: str, ticker: str, company_name: str | None) -> str:
    """The question for BM25 without the company and the year.

    Both are already filters, so in BM25 they only add noise: "Apple" and "2019" appear in
    hundreds of the filing's chunks and pull up notes that repeat them, ahead of the passage
    that answers. Measured on the 150 evaluation questions, exact chunk in the top 5 went
    from 133 to 142. The vector search keeps the full question.
    """
    query = question.replace("’", "'")
    words = company_name_words(company_name or "")
    if words:
        # "Cadence Design Systems'" or just "Cadence": the name's first word and the ones that follow it
        pattern = ""
        for word in reversed(words[1:]):
            pattern = rf"(?:\s+{re.escape(word)}{pattern})?"
        name = re.compile(rf"\b{re.escape(words[0])}{pattern}(?:'s\b|')?", re.IGNORECASE)
        query = name.sub(" ", query)
    # Case-sensitive: the ticker FAST is a company, "fast" is a word
    query = re.sub(rf"\b{re.escape(ticker.upper())}\b", " ", query)
    query = YEAR_MENTION.sub(" ", query)
    query = " ".join(query.split())
    return query if re.search(r"\w", query) else question


def build_filters(ticker: str, fiscal_year: int) -> dict[str, Any]:
    """Build the same exact metadata restriction for both retrievers."""
    normalized_ticker = ticker.strip().upper()
    if not TICKER.fullmatch(normalized_ticker):
        raise ValueError(f"invalid ticker: {ticker!r}")
    year = int(fiscal_year)
    if not 1990 <= year <= 2100:
        raise ValueError(f"invalid fiscal year: {year}")
    return {
        "operator": "AND",
        "conditions": [
            {"field": "ticker", "operator": "==", "value": normalized_ticker},
            {"field": "fiscal_year", "operator": "==", "value": year},
        ],
    }


def to_contract3(document: Document) -> dict[str, Any]:
    """Serialize one Haystack Document to the generation lane's Contract 3."""
    meta = document.meta or {}
    missing = [field for field in CONTRACT3_META if field not in meta]
    if missing:
        raise ValueError(f"document {document.id!r} is missing meta fields: {missing}")
    if document.content is None:
        raise ValueError(f"document {document.id!r} has no content")
    if document.score is None:
        raise ValueError(f"document {document.id!r} has no retrieval score")
    return {
        "chunk_id": document.id,
        "text": document.content,
        "score": float(document.score),
        **{field: meta[field] for field in CONTRACT3_META},
    }


@dataclass(frozen=True)
class RetrievalResult:
    bm25: list[Document]
    vector: list[Document]
    hybrid: list[Document]

    def documents(self, mode: str) -> list[Document]:
        if mode not in {"bm25", "vector", "hybrid"}:
            raise ValueError(f"unknown retrieval mode: {mode}")
        return getattr(self, mode)


class HybridRetriever:
    """Run both retrievers with identical filters and combine their rankings."""

    def __init__(
        self,
        *,
        text_embedder: Any,
        bm25_retriever: Any,
        vector_retriever: Any,
        joiner: Any,
        final_top_k: int = config.FINAL_TOP_K,
    ) -> None:
        self.text_embedder = text_embedder
        self.bm25_retriever = bm25_retriever
        self.vector_retriever = vector_retriever
        self.joiner = joiner
        self.final_top_k = final_top_k

    @classmethod
    def from_settings(
        cls,
        *,
        candidate_top_k: int = config.CANDIDATE_TOP_K,
        final_top_k: int = config.FINAL_TOP_K,
    ) -> HybridRetriever:
        if candidate_top_k < final_top_k or final_top_k < 1:
            raise ValueError("candidate_top_k must be >= final_top_k >= 1")

        from haystack.components.joiners import DocumentJoiner
        from haystack_integrations.components.embedders.sentence_transformers import (
            SentenceTransformersTextEmbedder,
        )
        from haystack_integrations.components.retrievers.elasticsearch import (
            ElasticsearchBM25Retriever,
            ElasticsearchEmbeddingRetriever,
        )

        config.validate()
        store = make_document_store()
        embedder = SentenceTransformersTextEmbedder(
            model=config.EMBEDDING_MODEL,
            prefix=config.QUERY_PREFIX,
            normalize_embeddings=True,
            progress_bar=False,
        )
        embedder.warm_up()
        return cls(
            text_embedder=embedder,
            bm25_retriever=ElasticsearchBM25Retriever(
                document_store=store, top_k=candidate_top_k
            ),
            vector_retriever=ElasticsearchEmbeddingRetriever(
                document_store=store, top_k=candidate_top_k
            ),
            joiner=DocumentJoiner(
                join_mode="reciprocal_rank_fusion", top_k=final_top_k
            ),
            final_top_k=final_top_k,
        )

    def run(self, question: str, ticker: str, fiscal_year: int) -> RetrievalResult:
        query = clean_question(question)
        filters = build_filters(ticker, fiscal_year)

        query_embedding = self.text_embedder.run(text=query)["embedding"]
        vector_candidates = self.vector_retriever.run(
            query_embedding=query_embedding, filters=filters
        )["documents"]
        # Every candidate comes from the same filing: its official name tells BM25 what to leave out
        company_name = vector_candidates[0].meta.get("company_name") if vector_candidates else None
        bm25_candidates = self.bm25_retriever.run(
            query=keyword_query(query, ticker, company_name), filters=filters
        )["documents"]
        hybrid = self.joiner.run(documents=[bm25_candidates, vector_candidates])[
            "documents"
        ]
        return RetrievalResult(
            bm25=bm25_candidates[: self.final_top_k],
            vector=vector_candidates[: self.final_top_k],
            hybrid=hybrid[: self.final_top_k],
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Search FilingLens with BM25, vectors, and RRF"
    )
    parser.add_argument("--question", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--mode", choices=("bm25", "vector", "hybrid"), default="hybrid"
    )
    parser.add_argument("--top-k", type=int, default=config.FINAL_TOP_K)
    parser.add_argument("--candidate-top-k", type=int, default=config.CANDIDATE_TOP_K)
    args = parser.parse_args(argv)

    retriever = HybridRetriever.from_settings(
        candidate_top_k=args.candidate_top_k, final_top_k=args.top_k
    )
    result = retriever.run(args.question, args.ticker, args.year)
    print(
        json.dumps([to_contract3(doc) for doc in result.documents(args.mode)], indent=2)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
