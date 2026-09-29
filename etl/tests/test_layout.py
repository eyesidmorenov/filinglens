from src.layout import is_table_row, is_year_header, rows_to_markdown


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
