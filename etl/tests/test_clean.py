from src.clean import clean_pages, is_page_number, join_hyphenated, normalize_whitespace


def test_join_hyphenated_word_split_across_lines():
    assert join_hyphenated("our manu-\nfacturing partners") == "our manufacturing partners"


def test_page_numbers():
    assert is_page_number("23")
    assert is_page_number("Page 7")
    assert is_page_number("iv")
    assert not is_page_number("2019")  # four digits: a year, not a page number
    assert not is_page_number("Net income")


def test_normalize_whitespace():
    assert normalize_whitespace("a  b\t\tc\n\n\n\nd") == "a b c\n\nd"


BODY = ["Our products compete on price.", "Demand may change.", "We depend on suppliers.",
        "Revenue is seasonal.", "Laws may change."]


def test_running_header_removed_when_repeated_on_many_pages():
    # Body lines differ in words, not only digits, like real paragraphs do
    pages = [[f"Apple Inc. | 2019 Form 10-K | {n}", *(f"{b} Topic {chr(64 + n)}." for b in BODY), str(n)]
             for n in range(1, 11)]
    cleaned = clean_pages(pages)
    assert all("Form 10-K" not in page for page in cleaned)
    assert cleaned[0].splitlines()[0] == f"{BODY[0]} Topic A."
    assert len(cleaned[0].splitlines()) == len(BODY)


def test_repeated_table_rows_in_the_middle_of_a_page_are_kept():
    pages = [["Header", "Intro text.", f"Basic | {n}.82 | {n}.11", "More text.", "Closing.", "Footer"]
             for n in range(10)]
    cleaned = clean_pages(pages)
    assert all("Basic |" in page for page in cleaned)
    assert all("Header" not in page and "Footer" not in page for page in cleaned)


def test_short_documents_keep_all_lines():
    pages = [["Title", "Text one."], ["Title", "Text two."]]
    assert clean_pages(pages) == ["Title\nText one.", "Title\nText two."]
