"""Helpers for the integration tests (no production logic)."""

from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent / "fixtures"
TEST_NAME_PREFIX = "test_"
DIMS = 768

# Official index mapping: a literal copy of index/src/documents.py::index_mapping(768)
# from the team repo (commit c37b08b). If the loader changes it, update it here too.
_KEYWORDS = ("doc_id", "section", "section_title", "company", "ticker", "doc_type", "chunk_type")
TEAM_MAPPING: dict[str, Any] = {
    "properties": {
        "content": {"type": "text", "analyzer": "english"},
        "embedding": {"type": "dense_vector", "dims": DIMS, "index": True, "similarity": "cosine"},
        **{field: {"type": "keyword"} for field in _KEYWORDS},
        "page": {"type": "integer"},
        "fiscal_year": {"type": "integer"},
    },
    "dynamic_templates": [
        {
            "strings": {
                "path_match": "*",
                "match_mapping_type": "string",
                "mapping": {"type": "keyword"},
            }
        }
    ],
}


def guard_test_name(name: str) -> str:
    """Tests never touch indices whose name does not start with ``test_``."""
    if not name.startswith(TEST_NAME_PREFIX):
        raise RuntimeError(
            f"Refusing to operate on {name!r}: tests only touch names that start with "
            f"{TEST_NAME_PREFIX!r}"
        )
    return name


def delete_test_indices(client: Any, prefix: str) -> list[str]:
    """Delete only the test's own ``<prefix>*`` indices."""
    guard_test_name(prefix)
    # Elasticsearch 8 forbids wildcard deletes by default: list them and delete by name.
    names = list(client.indices.get(index=f"{prefix}*", allow_no_indices=True))
    for name in names:
        client.indices.delete(index=guard_test_name(name))
    return names


def unit_vector(position: int) -> list[float]:
    vector = [0.0] * DIMS
    vector[position % DIMS] = 1.0
    return vector


def to_index_document(chunk: dict[str, Any], position: int) -> dict[str, Any]:
    """A synthetic chunk as the team loader leaves it in Elasticsearch."""
    return {
        "id": chunk["chunk_id"],
        "content": chunk["text"],
        "embedding": unit_vector(position),
        "doc_id": chunk["doc_id"],
        "section": chunk["section"],
        "section_title": "",
        "page": chunk["page"],
        "company": chunk["company"],
        "ticker": chunk["ticker"],
        "fiscal_year": chunk["fiscal_year"],
        "doc_type": "10-K",
        "chunk_type": "table" if chunk["section"] == "Item 8" else "text",
    }


def bulk_index(client: Any, index: str, chunks: list[dict[str, Any]]) -> None:
    guard_test_name(index)
    operations: list[dict[str, Any]] = []
    for position, chunk in enumerate(chunks):
        operations.append({"index": {"_index": index, "_id": chunk["chunk_id"]}})
        operations.append(to_index_document(chunk, position))
    response = client.bulk(operations=operations, refresh=True)
    assert not response["errors"], response
