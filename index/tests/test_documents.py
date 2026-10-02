from src import config
from src.documents import (
    chunk_to_document,
    company_name,
    context_header,
    embedding_text,
    index_mapping,
    mapping_problems,
)

CHUNK = {
    "chunk_id": "AAPL_2019_10K_p8_c1",
    "doc_id": "AAPL_2019_10K",
    "text": "Item 1A. Risk Factors ...",
    "section": "Item 1A",
    "page": 8,
    "company": "apple-inc",
    "ticker": "AAPL",
    "fiscal_year": 2019,
    "content_type": "text",
    "doc_type": "10-K",
}


def test_chunk_becomes_the_document_tenk_answer_expects():
    doc = chunk_to_document(CHUNK)
    assert doc.id == "AAPL_2019_10K_p8_c1"
    assert doc.content == "Item 1A. Risk Factors ..."
    # tenk-answer reads these four from meta (Contract 3)
    for field in ("section", "page", "company", "fiscal_year"):
        assert doc.meta[field] == CHUNK[field]
    # and search filters by these
    assert doc.meta["ticker"] == "AAPL" and doc.meta["doc_id"] == "AAPL_2019_10K"
    assert "text" not in doc.meta and "chunk_id" not in doc.meta


def test_reserved_name_is_renamed_so_it_stays_filterable():
    doc = chunk_to_document(CHUNK)
    assert doc.meta["chunk_type"] == "text"
    assert "content_type" not in doc.meta
    # Flattened as Elasticsearch stores it: a top-level field, not nested under "meta"
    flat = doc.to_dict(flatten=True)
    assert flat["chunk_type"] == "text" and "meta" not in flat


def test_section_title_is_added():
    assert chunk_to_document(CHUNK).meta["section_title"] == "Risk Factors"
    assert chunk_to_document({**CHUNK, "section": "Unknown"}).meta["section_title"] == ""


def test_context_header_is_embedded_but_not_stored():
    doc = chunk_to_document(CHUNK)
    assert company_name("nvidia-corporation") == "Nvidia Corporation"
    assert context_header(doc.meta) == "Apple Inc (AAPL) | Fiscal 2019 | Item 1A Risk Factors"
    assert embedding_text(doc) == "Apple Inc (AAPL) | Fiscal 2019 | Item 1A Risk Factors\nItem 1A. Risk Factors ..."
    assert doc.content == CHUNK["text"]  # what is cited stays the chunk text
    unknown = chunk_to_document({**CHUNK, "section": "Unknown"})
    assert context_header(unknown.meta) == "Apple Inc (AAPL) | Fiscal 2019"


def test_mapping_matches_the_model():
    props = index_mapping(768)["properties"]
    assert props["embedding"] == {"type": "dense_vector", "dims": 768, "index": True, "similarity": "cosine"}
    assert props["content"]["analyzer"] == "english"
    assert props["ticker"]["type"] == "keyword"
    assert props["section_title"]["type"] == "keyword"
    assert props["fiscal_year"]["type"] == "integer"


def test_mapping_problems_are_reported():
    expected = index_mapping(768)
    assert mapping_problems(expected, expected) == []
    # What Haystack's default store would have created
    default = {"properties": {"content": {"type": "text"},
                              "embedding": {"type": "dense_vector", "dims": 384, "similarity": "cosine"}}}
    problems = mapping_problems(default, expected)
    assert any("content" in p and "analyzer" in p for p in problems)
    assert any("embedding" in p and "dims" in p for p in problems)
    assert any("'ticker' is missing" in p for p in problems)


def test_defaults_shared_with_search():
    assert config.EMBEDDING_MODEL == "BAAI/bge-base-en-v1.5"
    assert config.EMBEDDING_DIMS == 768
    assert config.QUERY_PREFIX.startswith("Represent this sentence")
    assert config.ES_INDEX == "filinglens-chunks"
