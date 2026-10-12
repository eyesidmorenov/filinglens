"""health() without Elasticsearch: never raises and answers quickly."""

import time

from search_index import admin
from search_index.config import IndexSettings

UNREACHABLE = IndexSettings(es_url="http://localhost:1")


def test_health_reports_down_quickly_and_never_raises_when_nothing_answers():
    started = time.perf_counter()

    result = admin.health(UNREACHABLE)

    assert time.perf_counter() - started < 5
    assert set(result) == {"status", "cluster_status", "index_exists", "compatible", "detail"}
    assert result["status"] == "down"
    assert (result["cluster_status"], result["index_exists"], result["compatible"]) == (
        None,
        False,
        False,
    )
    assert result["detail"]
