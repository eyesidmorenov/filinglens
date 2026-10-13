"""Shared fixtures. Everything under tests/fixtures is SYNTHETIC (see fixtures/README.md)."""

import json
import os
import uuid
from pathlib import Path

import pytest
from es_helpers import (
    FIXTURES_DIR,
    TEAM_MAPPING,
    bulk_index,
    delete_test_indices,
    guard_test_name,
)


def pytest_collection_modifyitems(items):
    """The marker comes from the folder: nobody can forget to mark an Elasticsearch test."""
    for item in items:
        if "integration" in Path(str(item.fspath)).parts:
            item.add_marker(pytest.mark.integration)


@pytest.fixture
def dummy_chunks() -> list[dict]:
    """The 13 synthetic chunks."""
    lines = (FIXTURES_DIR / "chunks_dummy.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@pytest.fixture(scope="session")
def es_test_url() -> str:
    return os.environ.get("ES_TEST_HOSTS", "http://localhost:9200")


@pytest.fixture(scope="session")
def es_available(es_test_url):
    from elasticsearch import Elasticsearch

    client = Elasticsearch(es_test_url, request_timeout=2, max_retries=0)
    try:
        reachable = client.ping()
    finally:
        client.close()
    if not reachable:
        pytest.skip("Elasticsearch not available")


@pytest.fixture
def es_settings(es_available, es_test_url):
    """One index per test; cleanup only deletes ``<index>*``."""
    from search_index.config import IndexSettings
    from search_index.store import get_client

    index = guard_test_name(f"test_filinglens_{uuid.uuid4().hex[:8]}")
    settings = IndexSettings(es_url=es_test_url, index=index)
    yield settings
    with get_client(settings) as client:
        delete_test_indices(client, index)


@pytest.fixture
def es_client(es_settings):
    from search_index.store import get_client

    with get_client(es_settings) as client:
        yield client


@pytest.fixture
def team_index(es_settings, es_client) -> str:
    """Empty index created with the team loader's mapping."""
    es_client.indices.create(index=es_settings.index, mappings=TEAM_MAPPING)
    return es_settings.index


@pytest.fixture
def loaded(team_index, es_client, dummy_chunks) -> str:
    """The index holding the 13 synthetic chunks, as the loader would leave it."""
    bulk_index(es_client, team_index, dummy_chunks)
    return team_index
