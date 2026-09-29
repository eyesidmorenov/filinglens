from src.classify import classify

COVER = (
    "UNITED STATES\nSECURITIES AND EXCHANGE COMMISSION\nWashington, D.C. 20549\n"
    "FORM 10-K\nANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d)"
)


def test_pure_10k_starts_on_page_one_and_ends_at_signatures():
    pages = [COVER, "Item 1. Business", "Item 8. Financial Statements", "SIGNATURES\nPursuant to...", "Exhibit 10.1 credit agreement"]
    assert classify(pages) == ("10-K", (1, 4))


def test_wrapped_10k_starts_after_investor_material():
    pages = ["Dear shareholders", "Annual review", "Proxy statement", COVER, "Item 1A. Risk Factors", "SIGNATURES"]
    assert classify(pages) == ("10-K_wrapped", (4, 6))


def test_investor_only_report_has_no_10k():
    pages = ["Dear shareholders", "BUSINESS", "INCOME STATEMENTS", "Refer to Risk Factors in our Form 10-K"]
    assert classify(pages) == ("annual_report", None)


def test_a_mention_deep_in_a_page_is_not_a_cover():
    body = "x" * 2000 + COVER
    assert classify(["Dear shareholders", body]) == ("annual_report", None)


def test_missing_signatures_runs_to_the_last_page():
    assert classify([COVER, "Item 1", "Item 8"]) == ("10-K", (1, 3))
