"""health() and stats() against real Elasticsearch, on an index with the team's mapping."""

import copy
import json
import time

import pytest
from es_helpers import TEAM_MAPPING, bulk_index

from search_index import admin
from search_index.errors import IndexCompatibilityError
from search_index.store import assert_index_compatible


def test_health_is_ok_for_an_index_created_like_the_team_loader_does(es_settings, loaded):
    result = admin.health(es_settings)

    assert result["status"] == "ok"
    assert result["cluster_status"] in {"green", "yellow"}
    assert (result["index_exists"], result["compatible"]) == (True, True)
    assert_index_compatible(es_settings)


def test_health_is_degraded_when_the_index_does_not_exist_and_nothing_is_created(
    es_settings, es_client
):
    result = admin.health(es_settings)

    assert result["status"] == "degraded"
    assert (result["index_exists"], result["compatible"]) == (False, False)
    assert "--profile index run" in result["detail"]  # it says how to load it
    assert not es_client.indices.exists(index=es_settings.index)


def test_health_is_degraded_when_the_index_is_empty(es_settings, team_index):
    result = admin.health(es_settings)

    assert result["status"] == "degraded"
    assert (result["index_exists"], result["compatible"]) == (True, True)
    assert "empty" in result["detail"]


def test_health_is_degraded_when_the_dimensions_do_not_match_the_configuration(
    es_settings, loaded
):
    other = es_settings.model_copy(update={"embedding_dims": 384})

    result = admin.health(other)

    assert result["status"] == "degraded"
    assert (result["index_exists"], result["compatible"]) == (True, False)
    assert "384" in result["detail"] and "768" in result["detail"]
    with pytest.raises(IndexCompatibilityError, match="384"):
        assert_index_compatible(other)


def test_health_is_degraded_for_an_index_someone_else_created(es_settings, es_client):
    es_client.indices.create(index=es_settings.index)  # dynamic mapping, without our fields

    result = admin.health(es_settings)

    assert (result["status"], result["compatible"]) == ("degraded", False)
    assert "embedding" in result["detail"]


def test_health_is_degraded_when_the_cluster_is_red(es_settings, es_client, loaded):
    # An unassignable primary turns the cluster red; the index carries the test's prefix, so
    # cleanup deletes it and the cluster recovers.
    es_client.indices.create(
        index=f"{es_settings.index}_red",
        settings={"index.routing.allocation.require._name": "node-that-does-not-exist"},
        wait_for_active_shards="0",
    )
    deadline = time.monotonic() + 30
    while es_client.cluster.health().body["status"] != "red" and time.monotonic() < deadline:
        time.sleep(0.2)

    result = admin.health(es_settings)

    assert (result["cluster_status"], result["status"]) == ("red", "degraded")
    assert (result["index_exists"], result["compatible"]) == (True, True)


def test_stats_match_the_reference_counts_of_the_fixtures(es_settings, loaded):
    stats = admin.stats(es_settings)

    assert stats == {
        "index": loaded,
        "total_chunks": 13,
        "total_documents": 9,
        "by_company": {
            "NVIDIA Corporation": 4,
            "Apple Inc.": 3,
            "Tesla, Inc.": 2,
            "Amazon.com, Inc.": 1,
            "Intel Corporation": 1,
            "Meta Platforms, Inc.": 1,
            "Microsoft Corporation": 1,
        },
        "by_ticker": {"NVDA": 4, "AAPL": 3, "TSLA": 2, "AMZN": 1, "INTC": 1, "META": 1, "MSFT": 1},
        "by_fiscal_year": {2024: 11, 2023: 2},
        "by_section": {"Item 1A": 5, "Item 1": 4, "Item 7": 2, "Item 8": 2},
        "by_chunk_type": {"text": 11, "table": 2},
        "embedding_dims": 768,
    }
    json.dumps(stats)  # ready for /stats


def test_stats_do_not_truncate_past_ten_groups(es_settings, es_client, team_index):
    chunks = [
        {
            "chunk_id": f"T{n:02d}_2020_10K_p1_c1",
            "doc_id": f"T{n:02d}_2020_10K",
            "text": f"Synthetic filing number {n}.",
            "section": f"Item {n}",
            "page": 1,
            "company": f"company-{n:02d}",
            "ticker": f"T{n:02d}",
            "fiscal_year": 2000 + n,
        }
        for n in range(1, 26)
    ]
    bulk_index(es_client, team_index, chunks)

    stats = admin.stats(es_settings)

    assert stats["total_documents"] == 25
    assert len(stats["by_ticker"]) == len(stats["by_company"]) == 25
    assert len(stats["by_fiscal_year"]) == len(stats["by_section"]) == 25


def test_stats_refuse_a_missing_or_incompatible_index(es_settings, es_client):
    with pytest.raises(IndexCompatibilityError, match="does not exist"):
        admin.stats(es_settings)

    mapping = copy.deepcopy(TEAM_MAPPING)
    mapping["properties"]["ticker"] = {"type": "text"}
    es_client.indices.create(index=es_settings.index, mappings=mapping)
    with pytest.raises(IndexCompatibilityError, match="ticker"):
        admin.stats(es_settings)
