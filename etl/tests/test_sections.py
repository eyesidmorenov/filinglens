from src.sections import UNKNOWN, caption_item, is_toc_page, label_lines

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


def test_auditor_report_before_the_signatures_keeps_its_item():
    # Item 9A often carries the auditor's report on internal control
    pages = [
        ["Item 9A. Controls and Procedures", "Report of Independent Registered Public Accounting Firm", "We have audited."],
    ]
    assert set(label_lines(pages)[0]) == {"Item 9A"}
