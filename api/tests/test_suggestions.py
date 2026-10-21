"""Suggested questions (option A): templates, same company, only years we have, nothing Claude declines."""

import json

import pytest
from fastapi.testclient import TestClient

from app import main, pipeline, suggestions, yahoo

APPLE = {
    "ticker_10k": "AAPL",
    "currency": "USD",
    "fetched_at": "2026-10-20T14:03:11Z",
    "figures": {"Total Revenue": {"2023": 383285000000, "2024": 391035000000}},
}


@pytest.fixture
def apple_snapshot(tmp_path, monkeypatch):
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "snapshots" / "AAPL.json").write_text(json.dumps(APPLE), encoding="utf-8")
    monkeypatch.setattr(yahoo, "YAHOO_DIR", tmp_path)


def test_10k_year_with_yahoo(apple_snapshot):
    assert suggestions.suggest("What was Apple's total revenue in fiscal 2021?") == [
        "What were the main risk factors for Apple Inc. in fiscal 2021?",
        "What was the total revenue of Apple Inc. in fiscal 2020?",
        "What was the total revenue of Apple Inc. in fiscal 2024?",
    ]


def test_without_yahoo_only_10k_years():
    assert suggestions.suggest("What were Apple's main risk factors in fiscal 2020?") == [
        "What was the total revenue of Apple Inc. in fiscal 2020?",
        "What were the main risk factors for Apple Inc. in fiscal 2019?",
    ]


def test_first_10k_year_has_no_year_before():
    found = suggestions.suggest("What were Apple's main risk factors in fiscal 2019?")
    assert found == ["What was the total revenue of Apple Inc. in fiscal 2019?"]


def test_a_yahoo_year_only_suggests_yahoo_figures(apple_snapshot):
    found = suggestions.suggest("What was Apple's total revenue in fiscal 2024?")
    # Risk factors are not in the snapshot and this one has no net income: only revenue the year before
    assert found == ["What was the total revenue of Apple Inc. in fiscal 2023?"]


def test_unknown_topic_still_suggests_the_same_company(apple_snapshot):
    found = suggestions.suggest("Who audited Apple in fiscal 2021?")
    assert found == [
        "What was the total revenue of Apple Inc. in fiscal 2021?",
        "What was the total revenue of Apple Inc. in fiscal 2024?",
    ]


@pytest.mark.parametrize("question", ["What was the revenue?", "Tesla revenue in 2021", "Apple revenue in 2015"])
def test_no_suggestions_without_a_company_and_year_we_have(question):
    assert suggestions.suggest(question) == []


def test_every_suggestion_is_answerable_and_never_compares(apple_snapshot):
    for question in ("Apple revenue 2021", "Apple risk factors 2020", "Apple net income 2021"):
        for text in suggestions.suggest(question):
            assert pipeline.resolve_company_year(text)[2] is None
            assert not any(word in text.lower() for word in ("compare", "growth", "versus", "invest", "buy"))
        assert len(suggestions.suggest(question)) <= 3


def test_endpoint(apple_snapshot):
    response = TestClient(main.app).get("/suggestions", params={"question": "Apple revenue in fiscal 2021"})
    assert response.status_code == 200
    assert len(response.json()["suggestions"]) == 3


def test_endpoint_never_fails(monkeypatch):
    monkeypatch.setattr(main, "suggest", lambda q: 1 / 0)
    response = TestClient(main.app).get("/suggestions", params={"question": "anything"})
    assert response.json() == {"suggestions": []}


def test_a_yahoo_year_suggests_other_figures_it_has(tmp_path, monkeypatch):
    snapshot = dict(APPLE, figures={**APPLE["figures"], "Net Income": {"2024": 93736000000}})
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "snapshots" / "AAPL.json").write_text(json.dumps(snapshot), encoding="utf-8")
    monkeypatch.setattr(yahoo, "YAHOO_DIR", tmp_path)
    assert suggestions.suggest("What was Apple's total revenue in fiscal 2024?") == [
        "What was the net income of Apple Inc. in fiscal 2024?",
        "What was the total revenue of Apple Inc. in fiscal 2023?",
    ]
