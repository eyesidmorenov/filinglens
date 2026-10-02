"""
Integration checks against a running Elasticsearch with the index already loaded.
Skipped when Elasticsearch is not reachable or the index does not exist.
"""

import pytest
from elasticsearch import Elasticsearch

from src import config
from src.documents import index_mapping, mapping_problems, read_chunks


@pytest.fixture(scope="module")
def es() -> Elasticsearch:
    client = Elasticsearch(config.ES_URL)
    try:
        if not client.indices.exists(index=config.ES_INDEX):
            pytest.skip(f"index {config.ES_INDEX} not loaded")
    except Exception:
        pytest.skip(f"Elasticsearch not reachable at {config.ES_URL}")
    return client


def test_index_has_the_expected_mapping(es):
    actual = es.indices.get_mapping(index=config.ES_INDEX)[config.ES_INDEX]["mappings"]
    assert mapping_problems(actual, index_mapping(config.EMBEDDING_DIMS)) == []


def test_documents_keep_contract_fields(es):
    hit = es.search(index=config.ES_INDEX, size=1, query={"match_all": {}})["hits"]["hits"][0]
    source = hit["_source"]
    for field in ("content", "section", "section_title", "page", "company", "ticker",
                  "fiscal_year", "doc_id", "chunk_type"):
        assert field in source, field
    assert "meta" not in source  # nothing nested where filters can't reach it
    assert len(source["embedding"]) == config.EMBEDDING_DIMS


def test_index_matches_the_chunk_files_exactly(es):
    """No orphans and nothing missing: per document, the same ids as its .jsonl."""
    chunk_files = sorted((config.data_dir() / "chunks").glob("*.jsonl"))
    if not chunk_files:
        pytest.skip("no chunk files")
    agg = es.search(index=config.ES_INDEX, size=0,
                    aggs={"ids": {"terms": {"field": "doc_id", "size": 10_000}}})["aggregations"]["ids"]["buckets"]
    indexed = {b["key"]: b["doc_count"] for b in agg}
    expected = {f.stem: len(read_chunks(f)) for f in chunk_files}
    assert indexed == expected
