"""Environment-variable configuration, using the same names as the team repo."""

from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# IndexSettings field -> environment variable name (without prefix)
_ENV_VARS = {
    "es_url": "ELASTICSEARCH_URL",
    "index": "ES_INDEX",
    "embedding_dims": "EMBEDDING_DIMS",
}


class IndexSettings(BaseModel):
    """Where the official index lives and how many dimensions it must have. API keys do NOT live
    here: they are read from ``ELASTIC_API_KEY`` / ``ELASTIC_API_KEY_ID`` when connecting."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    es_url: str = "http://localhost:9200"
    index: str = Field(default="filinglens-chunks", min_length=1)
    embedding_dims: int = Field(default=768, gt=0)

    @field_validator("es_url")
    @classmethod
    def _url_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *, prefix: str = "") -> IndexSettings:
        """Read the configuration from ``env`` (defaults to ``os.environ``).

        ``prefix`` is prepended to every variable (``prefix="SEARCH_"`` reads ``SEARCH_ES_INDEX``)
        and unprefixed variables are ignored. Raises ``ValueError`` naming the invalid variable.
        """
        source = os.environ if env is None else env
        values = {
            field: source[prefix + name]
            for field, name in _ENV_VARS.items()
            if prefix + name in source
        }
        try:
            return cls(**values)
        except ValidationError as exc:
            problems = [
                f"{prefix}{_ENV_VARS[str(error['loc'][0])]}: {error['msg']}"
                for error in exc.errors()
            ]
            raise ValueError("Invalid configuration: " + "; ".join(problems)) from exc
