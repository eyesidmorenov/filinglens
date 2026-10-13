"""Read-only checks that prevent search from using an incompatible index."""

from typing import Any

from . import config


class IndexNotReadyError(RuntimeError):
    """The expected index is unavailable, empty, or has an incompatible mapping."""


EXPECTED_PROPERTIES = {
    "content": {"type": "text", "analyzer": "english"},
    "embedding": {
        "type": "dense_vector",
        "dims": config.EMBEDDING_DIMS,
        "similarity": "cosine",
    },
    "ticker": {"type": "keyword"},
    "fiscal_year": {"type": "integer"},
    "section": {"type": "keyword"},
    "page": {"type": "integer"},
    "company": {"type": "keyword"},
    "doc_id": {"type": "keyword"},
}


def mapping_problems(mapping: dict[str, Any]) -> list[str]:
    """Return the mapping differences that would make retrieval unreliable."""
    properties = mapping.get("properties", {})
    problems: list[str] = []
    for field, expected in EXPECTED_PROPERTIES.items():
        actual = properties.get(field)
        if actual is None:
            problems.append(f"field {field!r} is missing")
            continue
        for key, value in expected.items():
            if actual.get(key) != value:
                problems.append(
                    f"field {field!r}: {key} is {actual.get(key)!r}, expected {value!r}"
                )
    return problems


def verify_index(client: Any, require_documents: bool = True) -> int:
    """Verify the existing index without creating, deleting, or changing it."""
    if not client.ping():
        raise IndexNotReadyError(f"Elasticsearch is not reachable at {config.ES_URL}")
    if not client.indices.exists(index=config.ES_INDEX):
        raise IndexNotReadyError(
            f"Index {config.ES_INDEX!r} does not exist. Run the index loader first."
        )

    response = client.indices.get_mapping(index=config.ES_INDEX)
    mapping = response[config.ES_INDEX]["mappings"]
    problems = mapping_problems(mapping)
    if problems:
        raise IndexNotReadyError(
            f"Index {config.ES_INDEX!r} does not match the search contract:\n  - "
            + "\n  - ".join(problems)
        )

    count = int(client.count(index=config.ES_INDEX)["count"])
    if require_documents and count == 0:
        raise IndexNotReadyError(
            f"Index {config.ES_INDEX!r} exists but contains no chunks"
        )
    return count


def make_document_store():
    """Connect Haystack only after proving that the index already exists and is valid."""
    from elasticsearch import Elasticsearch
    from haystack_integrations.document_stores.elasticsearch import (
        ElasticsearchDocumentStore,
    )

    client = Elasticsearch(config.ES_URL)
    verify_index(client)
    return ElasticsearchDocumentStore(
        hosts=config.ES_URL,
        index=config.ES_INDEX,
        embedding_similarity_function="cosine",
    )
