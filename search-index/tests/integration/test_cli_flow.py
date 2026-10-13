"""The CLI against real Elasticsearch: health and stats on an index like the team's."""

import json

from search_index.__main__ import main


def test_health_and_stats_succeed_on_a_loaded_index(es_settings, loaded, capsys):
    env = {"ELASTICSEARCH_URL": es_settings.es_url, "ES_INDEX": es_settings.index}

    assert main(["health"], env=env) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    assert main(["stats"], env=env) == 0
    assert json.loads(capsys.readouterr().out)["total_chunks"] == 13


def test_health_exits_nonzero_when_the_index_is_missing(es_settings, capsys):
    env = {"ELASTICSEARCH_URL": es_settings.es_url, "ES_INDEX": es_settings.index}

    assert main(["health"], env=env) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "degraded"
