"""mapping_problems: which mapping differences would make reading the index unreliable."""

import copy

from es_helpers import TEAM_MAPPING

from search_index.store import mapping_problems


def properties(**changes):
    props = copy.deepcopy(TEAM_MAPPING["properties"])
    for field, spec in changes.items():
        if spec is None:
            del props[field]
        else:
            props[field] = spec
    return props


def test_the_team_mapping_has_no_problems():
    assert mapping_problems(properties(), dims=768) == []


def test_extra_details_reported_by_elasticsearch_are_not_problems():
    embedding = {
        "type": "dense_vector",
        "dims": 768,
        "index": True,
        "similarity": "cosine",
        "index_options": {"type": "int8_hnsw", "m": 16, "ef_construction": 100},
    }

    assert mapping_problems(properties(embedding=embedding, id={"type": "keyword"}), dims=768) == []


def test_other_dimensions_are_reported_with_both_numbers():
    (problem,) = mapping_problems(properties(), dims=384)

    assert "embedding" in problem and "768" in problem and "384" in problem


def test_a_missing_field_is_reported_by_name():
    assert mapping_problems(properties(chunk_type=None), dims=768) == [
        "field 'chunk_type' is missing"
    ]


def test_a_filter_field_mapped_as_text_is_reported():
    (problem,) = mapping_problems(properties(ticker={"type": "text"}), dims=768)

    assert "ticker" in problem and "keyword" in problem


def test_content_without_the_english_analyzer_is_reported():
    (problem,) = mapping_problems(properties(content={"type": "text"}), dims=768)

    assert "content" in problem and "english" in problem
