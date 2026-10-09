from datetime import date

from src.classify import classify, fiscal_year_end, year_check

COVER = (
    "UNITED STATES\nSECURITIES AND EXCHANGE COMMISSION\nWashington, D.C. 20549\n"
    "FORM 10-K\nANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d)"
)
SIGNATURE_PAGE = (
    "SIGNATURES\nPursuant to the requirements of Section 13 or 15(d) of the Securities Exchange Act of 1934, "
    "the Registrant has duly caused this report to be signed on its behalf by the undersigned."
)
CONTENTS = (
    "TABLE OF CONTENTS\nPART I\nItem 1. | Business | 4\nItem 1A. | Risk Factors | 13\n"
    "Item 1B. | Unresolved Staff Comments | 28\nItem 2. | Properties | 28\nItem 3. | Legal Proceedings | 28\n"
    "Item 4. | Mine Safety Disclosures | 28\nPART II\nItem 5. | Market for Registrant's Common Equity | 29\n"
    "Item 6. | Selected Financial Data | 30\nItem 7. | Management's Discussion and Analysis | 31\n"
    "Item 7A. | Quantitative and Qualitative Disclosures About Market Risk | 55\n"
    "Item 8. | Financial Statements and Supplementary Data | 56\nSIGNATURES | 120"
)


def test_pure_10k_starts_on_page_one_and_ends_at_signatures():
    pages = [COVER, "Item 1. Business", "Item 8. Financial Statements", SIGNATURE_PAGE, "Exhibit 10.1 credit agreement"]
    assert classify(pages) == ("10-K", (1, 4))


def test_wrapped_10k_starts_after_investor_material():
    pages = ["Dear shareholders", "Annual review", "Proxy statement", COVER, "Item 1A. Risk Factors", SIGNATURE_PAGE]
    assert classify(pages) == ("10-K_wrapped", (4, 6))


def test_investor_only_report_has_no_10k():
    pages = ["Dear shareholders", "BUSINESS", "INCOME STATEMENTS", "Refer to Item 1A Risk Factors in our Form 10-K"]
    assert classify(pages) == ("annual_report", None)


def test_a_mention_deep_in_a_page_is_not_a_cover():
    body = "x" * 2500 + COVER
    assert classify(["Dear shareholders", body]) == ("annual_report", None)


def test_an_exhibit_list_citing_a_10k_is_not_a_cover():
    # Fiserv 2021: exhibits "filed with the Securities and Exchange Commission ... on Form 10-K"
    exhibits = ("4.20 Twenty-Fifth Supplemental Indenture (14) Incorporated by reference to the Company's report "
                "filed with the Securities and Exchange Commission on Form 10-K for the year ended 2020")
    assert classify(["Annual report", exhibits]) == ("annual_report", None)


def test_signatures_in_the_table_of_contents_do_not_end_the_10k():
    # Facebook and IDEXX: the contents page lists "SIGNATURES", the real page comes much later
    pages = [COVER, CONTENTS, "Item 1. Business", "Item 8. Financial Statements", SIGNATURE_PAGE, "Exhibit 10.1"]
    assert classify(pages) == ("10-K", (1, 5))


def test_signature_page_without_the_section_13_wording():
    # Amgen and Illumina say only "the registrant has duly caused this report to be signed"
    amgen = "SIGNATURES\nThe registrant has duly caused this report to be signed on its behalf."
    assert classify([COVER, "Item 1", amgen, "Exhibit"]) == ("10-K", (1, 3))


def test_cover_as_an_image_starts_the_10k_at_its_table_of_contents():
    # Activision 2020: the cover page has no text, the contents page right after it does
    pages = ["Dear shareholders", "1", CONTENTS, "Item 1. Business", SIGNATURE_PAGE]
    assert classify(pages) == ("10-K_wrapped", (3, 5))


def test_missing_signatures_runs_to_the_last_page():
    assert classify([COVER, "Item 1", "Item 8"]) == ("10-K", (1, 3))


def test_fiscal_year_end_from_cover():
    assert fiscal_year_end(COVER + "\nFor the fiscal year ended September 28, 2019") == date(2019, 9, 28)
    # Rebuilt rows may split the sentence into cells
    assert fiscal_year_end("For the fiscal year ended | January 26, 2020") == date(2020, 1, 26)
    assert fiscal_year_end("FOR THE FISCAL YEAR ENDED DECEMBER 31, 2020") == date(2020, 12, 31)
    assert fiscal_year_end("Dear shareholders") is None


def test_year_check():
    assert year_check(2019, date(2019, 9, 28)) == "ok"
    assert year_check(2019, date(2020, 2, 1)) == "check"  # retail-style fiscal year naming
    assert year_check(2019, date(2021, 6, 30)) == "mismatch"
    assert year_check(2019, None) == "not found"


def test_financial_statements_after_the_signatures_stay_in_the_10k():
    # Qualcomm, Amgen, Dexcom, Vertex, Cognizant: F-pages after the signature page,
    # sometimes after a couple of exhibits; the exhibits that follow them are left out
    f_page = "CONSOLIDATED BALANCE SHEETS\nTotal assets | 32,957\nF-{}"
    pages = [COVER, "Item 8. See pages F-1 to F-3", SIGNATURE_PAGE, "EXHIBIT 23\nConsent", "EXHIBIT 24\nPower of attorney",
             f_page.format(1), f_page.format(2), "Cognizant | F-3 | December 31, 2021 Form 10-K",
             "Exhibit 10.1", "Exhibit 10.2", "Exhibit 10.3", "Exhibit 10.4", "Exhibit 99 | F-1"]
    assert classify(pages) == ("10-K", (1, 8))
