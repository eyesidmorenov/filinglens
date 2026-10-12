"""build_filters: Haystack filter syntax over meta.<field>."""

import pytest

from search_index.retrieval import build_filters


def test_without_arguments_there_is_no_filter():
    assert build_filters() is None


def test_a_single_value_is_an_equality_condition():
    assert build_filters(ticker="NVDA") == {
        "field": "meta.ticker",
        "operator": "==",
        "value": "NVDA",
    }


def test_several_fields_are_combined_with_and_in_a_stable_order():
    filters = build_filters(section="Item 1", fiscal_year=2024, ticker="AAPL", company="Apple Inc.")

    assert filters == {
        "operator": "AND",
        "conditions": [
            {"field": "meta.company", "operator": "==", "value": "Apple Inc."},
            {"field": "meta.ticker", "operator": "==", "value": "AAPL"},
            {"field": "meta.fiscal_year", "operator": "==", "value": 2024},
            {"field": "meta.section", "operator": "==", "value": "Item 1"},
        ],
    }


def test_a_list_becomes_an_in_condition():
    assert build_filters(ticker=["NVDA", "AAPL"]) == {
        "field": "meta.ticker",
        "operator": "in",
        "value": ["NVDA", "AAPL"],
    }


def test_list_and_scalar_mix_in_one_and():
    filters = build_filters(ticker=["NVDA", "AAPL"], fiscal_year=2024)

    assert filters == {
        "operator": "AND",
        "conditions": [
            {"field": "meta.ticker", "operator": "in", "value": ["NVDA", "AAPL"]},
            {"field": "meta.fiscal_year", "operator": "==", "value": 2024},
        ],
    }


@pytest.mark.parametrize(
    "kwargs",
    [{"ticker": []}, {"ticker": ""}, {"section": ""}, {"company": ["Apple Inc.", ""]}],
)
def test_empty_values_fail_early_instead_of_silently_matching_nothing(kwargs):
    with pytest.raises(ValueError, match=next(iter(kwargs))):
        build_filters(**kwargs)
