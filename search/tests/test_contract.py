import pytest
from haystack import Document
from src import config
from src.index_contract import IndexNotReadyError, mapping_problems, verify_index
from src.retrieval import build_filters, clean_question, to_contract3


def test_settings_match_the_index_lane():
    assert config.EMBEDDING_MODEL == "BAAI/bge-base-en-v1.5"
    assert config.EMBEDDING_DIMS == 768
    assert (
        config.QUERY_PREFIX
        == "Represent this sentence for searching relevant passages: "
    )
    assert config.ES_INDEX == "filinglens-chunks"


def test_filters_are_exact_and_normalized():
    assert build_filters(" aapl ", 2019) == {
        "operator": "AND",
        "conditions": [
            {"field": "ticker", "operator": "==", "value": "AAPL"},
            {"field": "fiscal_year", "operator": "==", "value": 2019},
        ],
    }
    with pytest.raises(ValueError):
        build_filters("not a ticker", 2019)


def test_question_is_cleaned_once_before_both_searches():
    assert clean_question("  What are\n the risks?  ") == "What are the risks?"
    with pytest.raises(ValueError):
        clean_question("  ")


def test_document_serializes_to_exact_contract3():
    document = Document(
        id="AAPL_2019_10K_p8_c1",
        content="A risk paragraph.",
        score=0.75,
        meta={
            "section": "Item 1A",
            "page": 8,
            "company": "apple-inc",
            "ticker": "AAPL",
            "fiscal_year": 2019,
            "doc_id": "AAPL_2019_10K",
        },
    )
    assert to_contract3(document) == {
        "chunk_id": "AAPL_2019_10K_p8_c1",
        "text": "A risk paragraph.",
        "score": 0.75,
        "section": "Item 1A",
        "page": 8,
        "company": "apple-inc",
        "fiscal_year": 2019,
    }


def test_mapping_mismatch_is_explained():
    problems = mapping_problems(
        {
            "properties": {
                "content": {"type": "text"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": 384,
                    "similarity": "cosine",
                },
            }
        }
    )
    assert any("analyzer" in problem for problem in problems)
    assert any("dims" in problem for problem in problems)
    assert any("ticker" in problem and "missing" in problem for problem in problems)


class _Indices:
    def exists(self, *, index):
        return False


class _MissingIndexClient:
    indices = _Indices()

    def ping(self):
        return True


def test_search_never_creates_a_missing_index():
    with pytest.raises(IndexNotReadyError, match="does not exist"):
        verify_index(_MissingIndexClient())
