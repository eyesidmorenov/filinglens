import pytest

from app import catalog, company_year, pipeline
from app.company_year import clarification_message, analyze_company_year, extract_company_year, short_name


def bucket(ticker, folder, years):
    """One ticker bucket, as the index aggregation returns it."""
    return {
        "key": ticker,
        "folder": {"buckets": [{"key": folder}] if folder else []},
        "years": {
            "buckets": [
                {"key": year, "name": {"buckets": [{"key": name}] if name else []}} for year, name in years
            ]
        },
    }


def test_the_catalog_is_built_from_the_index_aggregation():
    built = catalog.from_aggregation([
        bucket("FB", "meta-platforms-inc", [(2019, "Facebook, Inc."), (2021, "Meta Platforms, Inc.")]),
        bucket("KHC", "the-kraft-heinz-company", [(2020, "The Kraft Heinz Company")]),
    ])
    assert built.names == {
        ("FB", 2019): "Facebook, Inc.",
        ("FB", 2021): "Meta Platforms, Inc.",
        ("KHC", 2020): "The Kraft Heinz Company",
    }
    assert built.folders == {"FB": "meta-platforms-inc", "KHC": "the-kraft-heinz-company"}
    assert built.tickers == {"FB", "KHC"}
    assert built.years == (2019, 2020, 2021)


def test_an_index_without_company_name_falls_back_to_the_folder_name():
    built = catalog.from_aggregation([bucket("AAPL", "apple-inc", [(2019, None)])])
    assert built.names == {("AAPL", 2019): "Apple Inc"}


@pytest.mark.parametrize(
    ("official", "short"),
    [
        ("the kraft heinz company", "kraft heinz"),
        ("united airlines holdings inc", "united airlines"),
        ("marriott international inc", "marriott"),
        ("logitech international s a", "logitech"),
        ("seagate technology public limited company", "seagate technology"),
        ("texas instruments incorporated", "texas instruments"),
        ("apple inc", "apple"),
    ],
)
def test_short_name_drops_the_legal_endings(official, short):
    assert short_name(official) == short


def test_a_company_added_to_the_index_needs_no_code_change(monkeypatch, companies_from_fixture):
    names = dict(companies_from_fixture.names)
    names.update({("KHC", y): "The Kraft Heinz Company" for y in (2019, 2020, 2021)})
    names.update({("UAL", y): "United Airlines Holdings, Inc." for y in (2019, 2020, 2021)})
    folders = {**companies_from_fixture.folders, "KHC": "the-kraft-heinz-company", "UAL": "united-airlines-holdings-inc"}
    monkeypatch.setattr(catalog, "load", lambda: catalog.Catalog(names=names, folders=folders))
    company_year._catalog.cache_clear()

    assert extract_company_year("What risks did Kraft Heinz report in 2020?") == ("KHC", 2020)
    assert extract_company_year("United Airlines revenue in fiscal 2021") == ("UAL", 2021)
    assert clarification_message(analyze_company_year("Tesla revenue in 2021")) == (
        "Please mention one of the 27 supported NASDAQ companies."
    )
    assert pipeline.company_names()[("KHC", 2020)] == "The Kraft Heinz Company"


def test_nicknames_come_from_the_data_file():
    # "Gilead" and "IDEXX" can't be derived from "Gilead Sciences, Inc." or "IDEXX Laboratories, Inc."
    assert extract_company_year("Gilead product sales 2021") == ("GILD", 2021)
    assert extract_company_year("IDEXX legal proceedings 2021") == ("IDXX", 2021)


def test_a_too_generic_short_name_is_not_used_alone(monkeypatch, companies_from_fixture):
    names = {**companies_from_fixture.names, ("NDAQ", 2020): "Nasdaq, Inc."}
    folders = {**companies_from_fixture.folders, "NDAQ": "nasdaq-omx-group-inc"}
    monkeypatch.setattr(catalog, "load", lambda: catalog.Catalog(names=names, folders=folders))
    company_year._catalog.cache_clear()

    # "a NASDAQ company" is not Nasdaq, Inc.; its full name and its ticker still are
    assert extract_company_year("Which NASDAQ company is Apple? Revenue in 2020") == ("AAPL", 2020)
    assert extract_company_year("What did Nasdaq, Inc. report in 2020?") == ("NDAQ", 2020)
    assert extract_company_year("NDAQ revenue 2020") == ("NDAQ", 2020)


def test_the_years_in_the_messages_come_from_the_index(monkeypatch):
    names = {("AAPL", 2020): "Apple Inc.", ("AAPL", 2021): "Apple Inc."}
    monkeypatch.setattr(catalog, "load", lambda: catalog.Catalog(names=names, folders={"AAPL": "apple-inc"}))
    company_year._catalog.cache_clear()

    assert clarification_message(analyze_company_year("Apple risks")) == "Please specify a fiscal year: 2020 or 2021."
