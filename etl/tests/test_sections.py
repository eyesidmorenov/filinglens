from src.sections import ITEM_HEADING, UNKNOWN, caption_item, is_toc_page, label_lines

TOC = [
    "Item 1. | Business | 1",
    "Item 1A. | Risk Factors | 5",
    "Item 7. | Management's Discussion | 20",
    "Item 8. | Financial Statements | 30",
]


def test_table_of_contents_page_is_detected():
    assert is_toc_page(TOC)
    assert not is_toc_page(["Item 1A. Risk Factors", "Some text"])


def test_items_are_assigned_and_toc_is_ignored():
    pages = [
        ["Cover page"],
        TOC,
        ["Item 1. Business", "We design phones."],
        ["Item 1A. Risk Factors", "Supply may fail."],
        ["More risk text.", "Item 7. Management's Discussion", "Revenue grew."],
    ]
    labels = label_lines(pages)
    assert labels[0] == [UNKNOWN]
    assert set(labels[1]) == {UNKNOWN}  # TOC lines don't move the section
    assert labels[2] == ["Item 1", "Item 1"]
    assert labels[3] == ["Item 1A", "Item 1A"]
    assert labels[4] == ["Item 1A", "Item 7", "Item 7"]


def test_reference_inside_a_sentence_is_not_a_heading():
    pages = [["Item 1. Business", "as described in Item 7 of this report."]]
    assert label_lines(pages) == [["Item 1", "Item 1"]]


def test_sentence_starting_with_an_item_reference_is_not_a_heading():
    pages = [["Item 1. Business", "Item 7 of this Form 10-K under the heading MD&A.", "We design phones."]]
    assert label_lines(pages) == [["Item 1", "Item 1", "Item 1"]]


def test_heading_variants():
    for line in ["Item 1A. Risk Factors", "ITEM 7: MANAGEMENT'S DISCUSSION", "Item 8", "Item 2 | Properties",
                 "Item 9B Other Information"]:
        assert label_lines([[line]])[0][0].startswith("Item"), line


def test_captions_map_to_items_when_no_numbered_headings():
    assert caption_item("MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION") == "Item 7"
    assert caption_item("FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA") == "Item 8"
    assert caption_item("BUSINESS") == "Item 1"
    assert caption_item("Business") is None  # captions are all caps
    pages = [["Dear shareholders"], ["BUSINESS", "We make software."], ["INCOME STATEMENTS"]]
    assert label_lines(pages) == [[UNKNOWN], ["Item 1", "Item 1"], ["Item 1"]]


def test_financial_statements_after_the_signatures_go_back_to_item_8():
    # Qualcomm: Item 8 points to the F-pages, which come after the signature page
    pages = [
        ["Item 8. Financial Statements and Supplementary Data", "See pages F-1 through F-44."],
        ["Item 16. Form 10-K Summary", "None."],
        ["SIGNATURES", "Pursuant to the requirements of Section 13 or 15(d) of the Securities Exchange Act of 1934,"],
        ["Report of Independent Registered Public Accounting Firm", "We have audited the consolidated balance sheets.", "F-1"],
        ["CONSOLIDATED BALANCE SHEETS", "Total assets | 32,957", "F-2"],
    ]
    labels = label_lines(pages)
    assert labels[1] == ["Item 16", "Item 16"]
    assert set(labels[3]) == {"Item 8"}
    assert set(labels[4]) == {"Item 8"}


def test_financial_statements_start_item_8_in_a_10k_without_item_headings():
    # Illumina: the body uses captions only (no "Item N"), and the statements start with their index
    pages = [
        ["QUANTITATIVE AND QUALITATIVE DISCLOSURE ABOUT MARKET RISK", "Interest Rate Sensitivity"],
        ["CONSOLIDATED FINANCIAL STATEMENTS", "INDEX TO CONSOLIDATED FINANCIAL STATEMENTS | Page", "Balance Sheets | 45"],
        ["CONSOLIDATED BALANCE SHEETS", "Total assets | 7,316"],
    ]
    labels = label_lines(pages)
    assert labels[0] == ["Item 7A", "Item 7A"]
    assert labels[1] == ["Item 7A", "Item 8", "Item 8"]
    assert set(labels[2]) == {"Item 8"}


def test_auditor_report_before_the_signatures_keeps_its_item():
    # Item 9A often carries the auditor's report on internal control
    pages = [
        ["Item 9A. Controls and Procedures", "Report of Independent Registered Public Accounting Firm", "We have audited."],
    ]
    assert set(label_lines(pages)[0]) == {"Item 9A"}


def test_short_sections_in_a_row_are_not_a_table_of_contents():
    # Adobe 2021, page 36: Items 1B to 4 take a few lines each, all on one page
    page = [
        "ITEM 1B. UNRESOLVED STAFF COMMENTS", "None.",
        "ITEM 2. PROPERTIES", "Our corporate headquarters are in San Jose, California.",
        "ITEM 3. LEGAL PROCEEDINGS", "See Note 16 of our Notes to Consolidated Financial Statements.",
        "ITEM 4. MINE SAFETY DISCLOSURES", "Not applicable.",
    ]
    assert not is_toc_page(page)
    labels = label_lines([["ITEM 1A. RISK FACTORS", "Our business could suffer."], page])
    assert labels[1][4:6] == ["Item 3", "Item 3"]


def test_a_long_list_of_items_is_a_table_of_contents_even_without_page_numbers():
    items = ["1", "1A", "1B", "2", "3", "4", "5", "6", "7", "7A", "8", "9", "9A", "9B", "10", "11"]
    assert is_toc_page([f"Item {n}. Heading" for n in items])


def test_a_reference_to_an_item_with_a_letter_is_not_a_heading():
    # "Item 1A of this report" used to be read as the heading "Item 1" followed by "A"
    for line in [
        "Item 1A of this report for further discussion of the pandemic.",
        "Item 7A, “Quantitative and Qualitative Disclosures about Market Risk” for further discussion.",
        'Item 1A, "Risk Factors-Our business is subject to complex laws."',
    ]:
        assert not ITEM_HEADING.match(line), line
    assert ITEM_HEADING.match("ITEM 1A. RISK FACTORS").group(1) == "1A"
    assert ITEM_HEADING.match("Item 9C. Disclosure Regarding Foreign Jurisdictions").group(1) == "9C"


def test_financial_statements_after_item_16_go_back_to_item_8():
    # Activision: the financial statements follow Item 16, before the signature page
    pages = [
        ["ITEM 15. EXHIBITS, FINANCIAL STATEMENT SCHEDULES", "Report of Independent Registered Public Accounting Firm | F-2"],
        ["ITEM 16. FORM 10-K SUMMARY", "Not applicable."],
        ["Report of Independent Registered Public Accounting Firm", "We have audited the balance sheets.", "F-2"],
    ]
    labels = label_lines(pages)
    assert labels[0] == ["Item 15", "Item 15"]  # a line of the Item 15 list is not the statements themselves
    assert set(labels[2]) == {"Item 8"}


def test_heading_in_the_last_cell_of_a_two_column_line_starts_its_item():
    # Xcel Energy: the right column's heading sits after a line of the left column
    pages = [["Item 7. Management's Discussion", "of common stock. | ITEM 7A — QUANTITATIVE AND QUALITATIVE DISCLOSURES",
              "Interest rates."]]
    assert label_lines(pages) == [["Item 7", "Item 7A", "Item 7A"]]


def test_a_reference_in_the_last_cell_is_not_a_heading():
    pages = [["Item 1. Business", "with the expertise to | Item 1A. Risk Factors included in this report.",
              "pages | Item 8."]]
    assert label_lines(pages) == [["Item 1", "Item 1", "Item 1"]]


def test_a_quoted_subsection_is_a_reference_not_a_heading():
    # American Airlines: "see Part I, Item 1A. Risk Factors – “The outbreak of COVID-19...”"
    pages = [["Item 1. Business", "For more information, see Part I,",
              "Item 1A. Risk Factors – “The outbreak and global spread of COVID-19”", "We fly planes."]]
    assert label_lines(pages) == [["Item 1"] * 4]
