"""Filtered BM25 + vector retrieval, fused with Haystack's RRF joiner."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from typing import Any

from haystack import Document

from . import config
from .index_contract import make_document_store

TICKER = re.compile(r"^[A-Z0-9.\-]{1,12}$")
CONTRACT3_META = ("section", "page", "company", "fiscal_year")


def clean_question(question: str) -> str:
    value = " ".join(question.split())
    if not value:
        raise ValueError("question must not be empty")
    return value


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

        bm25_candidates = self.bm25_retriever.run(query=query, filters=filters)[
            "documents"
        ]
        query_embedding = self.text_embedder.run(text=query)["embedding"]
        vector_candidates = self.vector_retriever.run(
            query_embedding=query_embedding, filters=filters
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
