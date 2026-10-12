"""IndexSettings.from_env: team variable names, early validation and prefix."""

import pytest

from search_index.config import IndexSettings


def test_defaults_are_the_team_index_and_model_dimensions():
    s = IndexSettings.from_env({})

    assert s.es_url == "http://localhost:9200"
    assert s.index == "filinglens-chunks"
    assert s.embedding_dims == 768


def test_the_team_variable_names_are_respected():
    env = {
        "ELASTICSEARCH_URL": "http://elasticsearch:9200",
        "ES_INDEX": "other",
        "EMBEDDING_DIMS": "384",
    }

    s = IndexSettings.from_env(env)

    assert (s.es_url, s.index, s.embedding_dims) == ("http://elasticsearch:9200", "other", 384)


def test_from_env_without_mapping_reads_the_process_environment(monkeypatch):
    monkeypatch.setenv("ES_INDEX", "from-the-environment")

    assert IndexSettings.from_env().index == "from-the-environment"


@pytest.mark.parametrize(
    ("env", "var"),
    [
        ({"EMBEDDING_DIMS": "0"}, "EMBEDDING_DIMS"),
        ({"EMBEDDING_DIMS": "abc"}, "EMBEDDING_DIMS"),
        ({"ES_INDEX": ""}, "ES_INDEX"),
        ({"ELASTICSEARCH_URL": " "}, "ELASTICSEARCH_URL"),
    ],
)
def test_invalid_values_are_rejected_naming_the_environment_variable(env, var):
    with pytest.raises(ValueError, match=var):
        IndexSettings.from_env(env)


def test_prefix_reads_only_prefixed_variables_and_names_them_in_errors():
    env = {"SEARCH_ES_INDEX": "prefixed", "ES_INDEX": "ignored"}

    assert IndexSettings.from_env(env, prefix="SEARCH_").index == "prefixed"
    with pytest.raises(ValueError, match="SEARCH_EMBEDDING_DIMS"):
        IndexSettings.from_env({"SEARCH_EMBEDDING_DIMS": "0"}, prefix="SEARCH_")


def test_api_keys_never_become_part_of_the_settings():
    s = IndexSettings.from_env({"ELASTIC_API_KEY": "super-secret"})

    assert "super-secret" not in repr(s)
