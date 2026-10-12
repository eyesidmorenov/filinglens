"""READ-ONLY access to the official index: client and mapping check.

The index is created and filled by the team loader (``index/src/load.py``). This module never
creates, modifies or deletes anything in Elasticsearch.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from elasticsearch import Elasticsearch

from .config import IndexSettings
from .errors import IndexCompatibilityError

_LOADER_HINT = "Load it with the team loader: `docker compose --profile index run --rm index`"

# Fields read by search and stats, as index/src/documents.py creates them.
_KEYWORD_FIELDS = ("doc_id", "section", "company", "ticker", "chunk_type")
_INTEGER_FIELDS = ("page", "fiscal_year")


def _api_key_from_env() -> str | tuple[str, str] | None:
    """``ELASTIC_API_KEY[_ID]``, as Haystack does. Never stored or printed."""
    api_key = os.environ.get("ELASTIC_API_KEY") or None
    api_key_id = os.environ.get("ELASTIC_API_KEY_ID") or None
    if api_key_id and not api_key:
        raise ValueError("ELASTIC_API_KEY_ID is set but ELASTIC_API_KEY is missing")
    if api_key_id and api_key:
        return (api_key_id, api_key)
    return api_key


def get_client(settings: IndexSettings, **kwargs: Any) -> Elasticsearch:
    """Elasticsearch client. Use ``with`` to close it. Accepts the client's kwargs."""
    return Elasticsearch(settings.es_url, api_key=_api_key_from_env(), **kwargs)


@dataclass(frozen=True)
class IndexInfo:
    """Physical index name and the properties of its mapping."""

    name: str
    properties: dict[str, Any] = field(default_factory=dict)


def describe_index(client: Elasticsearch, target: str) -> IndexInfo | None:
    """Read the mapping of ``target``. Returns ``None`` if it does not exist; never creates it."""
    if not client.indices.exists(index=target):
        return None
    mappings = client.indices.get_mapping(index=target).body
    if len(mappings) != 1:
        raise IndexCompatibilityError(
            f"{target!r} points to {len(mappings)} indices ({', '.join(sorted(mappings))}); "
            "it must be exactly one."
        )
    ((name, body),) = mappings.items()
    return IndexInfo(name=name, properties=body.get("mappings", {}).get("properties", {}))


def mapping_problems(properties: dict[str, Any], *, dims: int) -> list[str]:
    """Differences from the loader's mapping that would make reading the index unreliable."""
    expected: dict[str, dict[str, Any]] = {
        "content": {"type": "text", "analyzer": "english"},
        "embedding": {"type": "dense_vector", "dims": dims, "similarity": "cosine"},
        **{name: {"type": "keyword"} for name in _KEYWORD_FIELDS},
        **{name: {"type": "integer"} for name in _INTEGER_FIELDS},
    }
    problems = []
    for name, spec in expected.items():
        actual = properties.get(name)
        if actual is None:
            problems.append(f"field {name!r} is missing")
            continue
        for key, value in spec.items():
            if actual.get(key) != value:
                problems.append(
                    f"field {name!r}: {key} is {actual.get(key)!r}, expected {value!r}"
                )
    return problems


def require_compatible_index(client: Elasticsearch, settings: IndexSettings) -> IndexInfo:
    """Return the index if it exists and fits; else raise ``IndexCompatibilityError``."""
    info = describe_index(client, settings.index)
    if info is None:
        raise IndexCompatibilityError(f"Index {settings.index!r} does not exist. {_LOADER_HINT}.")
    problems = mapping_problems(info.properties, dims=settings.embedding_dims)
    if problems:
        raise IndexCompatibilityError(
            f"Index {info.name!r} does not have the expected mapping (EMBEDDING_DIMS="
            f"{settings.embedding_dims}): " + "; ".join(problems) + ". Check the configuration "
            "or rebuild the index with the loader (`python -m src.load --recreate`)."
        )
    return info


def assert_index_compatible(settings: IndexSettings) -> None:
    """Check that the index exists and has the loader's mapping; changes nothing."""
    with get_client(settings) as client:
        require_compatible_index(client, settings)
