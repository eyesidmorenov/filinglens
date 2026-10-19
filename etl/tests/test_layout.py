from src.layout import column_rows, is_table_row, is_year_header, rows_to_markdown, two_column_gutter


def test_table_row_needs_a_label_and_two_numbers():
    assert is_table_row(["Net income", "55,256", "59,531", "48,351"])
    assert is_table_row(["Interest expense", "(52)", "(58)", "—"])
    assert is_table_row(["Revenue", "100.0%", "100.0%"])
    assert not is_table_row(["Net income", "55,256"])
    assert not is_table_row(["We sell phones", "and services"])


def test_year_row_is_a_header_not_data():
    assert is_year_header(["Year Ended June 30,", "2020", "2019", "2018"])
    assert not is_year_header(["Net income", "44,281", "39,240", "16,571"])


def test_markdown_keeps_numbers_under_their_year():
    md = rows_to_markdown(
        [["2019", "2018"], ["Net sales:"], ["Total net sales", "260,174", "265,595"]],
        header_rows=1,
    )
    lines = md.splitlines()
    assert lines[0] == "|  | 2019 | 2018 |"
    assert lines[2] == "| Net sales: |  |  |"  # label goes to the first column
    assert lines[3] == "| Total net sales | 260,174 | 265,595 |"


def test_two_header_rows_are_merged():
    md = rows_to_markdown(
        [["September 28,", "September 29,"], ["2019", "2018"], ["Net income", "55,256", "59,531"]],
        header_rows=2,
    )
    assert md.splitlines()[0] == "|  | September 28, 2019 | September 29, 2018 |"


def words_on(rows, x0, size=5.0):
    """Fake pymupdf words: each row is a list of words written from x0, one per 30 points."""
    return [(x0 + 30 * i, 20 * r, x0 + 30 * i + 25, 20 * r + size, w, 0, 0, 0)
            for r, line in enumerate(rows) for i, w in enumerate(line.split())]


LEFT = ["the company sells many products"] * 10
RIGHT = ["risk factors may affect results"] * 10


def test_two_columns_of_prose_have_a_gutter_and_are_read_one_after_the_other():
    words = words_on(LEFT, 40) + words_on(["ITEM 1A risk factors may affect"] + RIGHT[1:], 330)
    gutter = two_column_gutter(words, 612)
    assert gutter is not None and 190 < gutter < 330
    rows = column_rows(words, gutter)
    assert rows[:10] == [["the company sells many products"]] * 10
    assert rows[10] == ["ITEM 1A risk factors may affect"]


def test_one_column_page_has_no_gutter():
    words = words_on(["the company sells many products in all of its markets"] * 20, 40)
    assert two_column_gutter(words, 612) is None


def test_a_table_is_not_two_columns():
    table = ["Revenue of the year | 1,200 2,300 3,400"] * 10
    words = words_on([r.split(" | ")[0] for r in table], 40) + words_on(["1,200 2,300 3,400 4,500"] * 10, 330)
    assert two_column_gutter(words, 612) is None
