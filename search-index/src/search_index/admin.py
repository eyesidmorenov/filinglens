"""Status and counts of the official index, ready for ``/health`` and ``/stats``. Read-only."""

from __future__ import annotations

from typing import Any

from .config import IndexSettings
from .errors import IndexCompatibilityError
from .store import get_client, require_compatible_index

_GOOD_CLUSTER_STATUS = {"green", "yellow"}


def _buckets(aggregation: dict[str, Any]) -> dict[Any, int]:
    return {bucket["key"]: bucket["doc_count"] for bucket in aggregation["buckets"]}


def stats(settings: IndexSettings) -> dict[str, Any]:
    """Index counts (everything is JSON-serializable).

    ``total_chunks`` is the number of chunks and ``total_documents`` the number of distinct
    ``doc_id`` values. Raises ``IndexCompatibilityError`` if the index does not exist or does not
    have the expected mapping.
    """
    with get_client(settings) as client:
        info = require_compatible_index(client, settings)
        total = client.count(index=settings.index)["count"]
        aggregations = client.search(
            index=settings.index,
            size=0,
            aggs={
                # Maximum precision_threshold: exact count far above our scale.
                "documents": {"cardinality": {"field": "doc_id", "precision_threshold": 40000}},
                "by_company": {"terms": {"field": "company", "size": 1000}},
                "by_ticker": {"terms": {"field": "ticker", "size": 1000}},
                "by_fiscal_year": {"terms": {"field": "fiscal_year", "size": 200}},
                "by_section": {"terms": {"field": "section", "size": 500}},
                "by_chunk_type": {"terms": {"field": "chunk_type", "size": 50}},
            },
        )["aggregations"]
    return {
        "index": info.name,
        "total_chunks": total,
        "total_documents": aggregations["documents"]["value"],
        "by_company": _buckets(aggregations["by_company"]),
        "by_ticker": _buckets(aggregations["by_ticker"]),
        "by_fiscal_year": _buckets(aggregations["by_fiscal_year"]),
        "by_section": _buckets(aggregations["by_section"]),
        "by_chunk_type": _buckets(aggregations["by_chunk_type"]),
        "embedding_dims": info.properties["embedding"]["dims"],
    }


def health(settings: IndexSettings) -> dict[str, Any]:
    """Status for ``/health``. NEVER raises and uses short timeouts.

    ``status``: ``ok`` (cluster green or yellow; index exists, is compatible and has chunks),
    ``degraded`` (Elasticsearch answers but something is off; ``detail`` says what) or ``down``.
    """
    result: dict[str, Any] = {
        "status": "down",
        "cluster_status": None,
        "index_exists": False,
        "compatible": False,
        "detail": "",
    }
    try:
        with get_client(settings, request_timeout=2, max_retries=0) as client:
            result["cluster_status"] = client.cluster.health().body["status"]
            result["status"] = "degraded"
            result["index_exists"] = bool(client.indices.exists(index=settings.index))
            try:
                require_compatible_index(client, settings)
            except IndexCompatibilityError as exc:
                result["detail"] = str(exc)
                return result
            result["compatible"] = True
            chunks = client.count(index=settings.index)["count"]
    except Exception as exc:  # noqa: BLE001 - health never raises
        result.update(status="down", index_exists=False, compatible=False)
        result["detail"] = f"Elasticsearch is not responding: {type(exc).__name__}: {exc}"[:300]
        return result

    if chunks == 0:
        result["detail"] = f"Index {settings.index!r} exists but is empty."
    elif result["cluster_status"] not in _GOOD_CLUSTER_STATUS:
        result["detail"] = f"The cluster status is {result['cluster_status']}."
    else:
        result.update(status="ok", detail="ok")
    return result
