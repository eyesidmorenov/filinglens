"""
Data contracts produced by this lane, as pydantic models.

Validating here means a missing or mistyped field fails in the ETL, not later
inside somebody else's index. Field names follow the team contracts in the
repository README.

Fields marked PROPOSED were suggested to the team and are optional until the
contracts are approved; consumers that don't know them can ignore them.
"""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

DocType = Literal["10-K", "10-K_wrapped", "annual_report"]
ContentType = Literal["text", "table", "image"]


class Page(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1, description="1-based page number in the PDF")
    text: str


class Document(BaseModel):
    """Contract 1: output of extraction, input of chunking (data/clean/<doc_id>.json)."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str
    company: str
    ticker: str
    fiscal_year: int
    exchange: str
    s3_key: str
    local_path: str
    size_mb: float
    n_pages: int = Field(ge=1)
    # PROPOSED
    doc_type: Optional[DocType] = None
    form_10k_pages: Optional[tuple[int, int]] = None
    pages: list[Page] = Field(default_factory=list)
    # Internal to this lane (contract 1 is produced and consumed only by the ETL)
    fiscal_year_end: Optional[date] = Field(default=None, description="From the 10-K cover")
    etl_fingerprint: Optional[str] = Field(default=None, description="Code and settings that produced it")


class Chunk(BaseModel):
    """Contract 2: output of chunking, input of indexing (data/chunks/<doc_id>.jsonl)."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    doc_id: str
    text: str = Field(min_length=1)
    section: str
    page: int = Field(ge=1, description="PDF page where the chunk starts")
    company: str
    ticker: str
    fiscal_year: int
    # PROPOSED
    content_type: ContentType = "text"
    doc_type: Optional[DocType] = None
