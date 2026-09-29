"""Public types: Contract 3 input (`SearchResult`) and the `Answer` that serializes to Contract 4."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from haystack import Document
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tenk_answer.errors import InvalidDocumentError

# Keys of Contract 3 that travel in `Document.meta`.
_META_FIELDS = ("section", "page", "company", "fiscal_year")


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    INSUFFICIENT_CONTEXT = "insufficient_context"
    OUT_OF_SCOPE = "out_of_scope"


class SearchResult(BaseModel):
    """One retrieved chunk, mirroring Contract 3. Unknown extra keys are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore", strict=False)

    chunk_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    score: float
    section: str = Field(min_length=1)
    page: int
    company: str = Field(min_length=1)
    fiscal_year: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SearchResult:
        """Validate a Contract 3 dict, raising `InvalidDocumentError` on missing or invalid fields."""
        try:
            return cls.model_validate(data)
        except ValidationError as e:
            chunk_id = data.get("chunk_id", "<unknown>") if isinstance(data, dict) else "<unknown>"
            raise InvalidDocumentError(f"Invalid search result {chunk_id!r}: {e}") from e

    @classmethod
    def from_document(cls, document: Document) -> SearchResult:
        """Map a Haystack `Document` (id/content/score/meta) back to Contract 3."""
        meta = document.meta or {}
        missing = [f for f in _META_FIELDS if f not in meta]
        if missing:
            raise InvalidDocumentError(f"Document {document.id!r} is missing meta fields: {missing}")
        return cls.from_dict(
            {
                "chunk_id": document.id,
                "text": document.content,
                "score": document.score,
                **{f: meta[f] for f in _META_FIELDS},
            }
        )

    def to_document(self) -> Document:
        return Document(
            id=self.chunk_id,
            content=self.text,
            score=self.score,
            meta={f: getattr(self, f) for f in _META_FIELDS},
        )


class Source(BaseModel):
    company: str
    fiscal_year: int
    section: str
    page: int
    excerpt: str
    chunk_id: str  # internal; never part of the API response


class Answer(BaseModel):
    status: AnswerStatus
    answer: str
    sources: list[Source] = Field(default_factory=list)
    latency_ms: int = 0
    model: str = ""
    usage: dict[str, Any] = Field(default_factory=dict)

    def to_api_response(self) -> dict[str, Any]:
        """Serialize to exactly Contract 4 (no status, chunk_id, model or usage)."""
        return {
            "answer": self.answer,
            "sources": [
                {
                    "company": s.company,
                    "fiscal_year": s.fiscal_year,
                    "section": s.section,
                    "page": s.page,
                    "excerpt": s.excerpt,
                }
                for s in self.sources
            ],
            "latency_ms": self.latency_ms,
        }
