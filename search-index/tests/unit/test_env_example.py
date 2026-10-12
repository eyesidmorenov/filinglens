""".env.example documents every variable, works as is and carries no secrets."""

from pathlib import Path

from search_index.config import _ENV_VARS, IndexSettings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def parse(text: str) -> dict[str, str]:
    pairs = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            pairs[key.strip()] = value.strip()
    return pairs


def test_it_defines_every_variable_and_loads_to_the_defaults():
    values = parse(ENV_EXAMPLE.read_text())

    assert set(_ENV_VARS.values()) <= set(values)
    assert IndexSettings.from_env(values) == IndexSettings()


def test_credentials_are_present_but_empty():
    values = parse(ENV_EXAMPLE.read_text())

    assert values["ELASTIC_API_KEY"] == "" and values["ELASTIC_API_KEY_ID"] == ""
