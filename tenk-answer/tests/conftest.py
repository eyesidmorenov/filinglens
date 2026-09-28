from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tenk_answer import SearchResult

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def raw_results() -> dict[str, dict[str, Any]]:
    data = json.loads((FIXTURES / "search_results.json").read_text())
    return {item["chunk_id"]: item for item in data}


@pytest.fixture(scope="session")
def results(raw_results: dict[str, dict[str, Any]]) -> dict[str, SearchResult]:
    return {cid: SearchResult.from_dict(item) for cid, item in raw_results.items()}


@pytest.fixture(scope="session")
def contract4_schema() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads((FIXTURES / "contract4.schema.json").read_text())
    return schema
