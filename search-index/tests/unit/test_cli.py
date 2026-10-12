"""CLI (python -m search_index): usage, exit codes and errors, without Elasticsearch."""

import json
import subprocess
import sys

import pytest

from search_index.__main__ import main

UNREACHABLE = {"ELASTICSEARCH_URL": "http://localhost:1"}


def run_cli(argv, env, capsys):
    code = main(argv, env=env)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_help_lists_both_commands_when_run_as_a_module():
    out = subprocess.run(
        [sys.executable, "-m", "search_index", "--help"], capture_output=True, text=True, check=True
    )

    assert "health" in out.stdout and "stats" in out.stdout


def test_health_prints_json_and_exits_nonzero_when_elasticsearch_is_down(capsys):
    code, out, _ = run_cli(["health"], UNREACHABLE, capsys)

    assert json.loads(out)["status"] == "down"
    assert code == 1


def test_a_failing_command_prints_a_one_line_error_and_exits_nonzero(capsys):
    code, out, err = run_cli(["stats"], UNREACHABLE, capsys)

    assert (code, out) == (1, "")
    assert err.startswith("error:") and "Traceback" not in err


def test_invalid_configuration_exits_with_usage_status_naming_the_variable(capsys):
    code, _, err = run_cli(["health"], {"EMBEDDING_DIMS": "0"}, capsys)

    assert code == 2 and "EMBEDDING_DIMS" in err


def test_env_prefix_makes_the_cli_read_prefixed_variables_and_ignore_the_rest(capsys):
    env = {"SEARCH_EMBEDDING_DIMS": "0", **UNREACHABLE}

    code, _, err = run_cli(["--env-prefix", "SEARCH_", "health"], env, capsys)
    assert code == 2 and "SEARCH_EMBEDDING_DIMS" in err

    code, out, _ = run_cli(["health"], env, capsys)
    assert code == 1 and json.loads(out)["status"] == "down"


def test_unknown_commands_are_a_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        main(["reindex"], env=UNREACHABLE)

    assert excinfo.value.code == 2
