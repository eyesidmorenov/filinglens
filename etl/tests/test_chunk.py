from src.chunk import CHUNK_WORDS, chunk_document, split_sentences, window_sentences
from src.models import Chunk, Document, Page

META = dict(
    doc_id="AAPL_2019_10K", company="apple-inc", ticker="AAPL", fiscal_year=2019,
    exchange="NASDAQ", s3_key="nasdaq_annual_reports/apple-inc/NASDAQ_AAPL_2019.pdf",
    local_path="data/raw/AAPL_2019.pdf", size_mb=5.25, n_pages=40, doc_type="10-K",
    form_10k_pages=(1, 40),
)


def sentence(i: int) -> str:
    return f"This is risk sentence number {i} about supply chains and demand."


def make_doc() -> Document:
    risk = "\n".join(sentence(i) for i in range(120))  # ~1,300 words
    statement = "\n".join([
        "CONSOLIDATED STATEMENTS OF OPERATIONS",
        "2019 | 2018 | 2017",
        "Net sales:",
        "Total net sales | 260,174 | 265,595 | 229,234",
        "Operating expenses:",
        "Research and development | 16,217 | 14,236 | 11,581",
        "Net income | 55,256 | 59,531 | 48,351",
    ])
    return Document(**META, pages=[
        Page(page=8, text="Item 1A. Risk Factors\n" + risk),
        Page(page=32, text="Item 8. Financial Statements and Supplementary Data\n" + statement),
    ])


def test_sentences_keep_the_page_where_they_start():
    words = [(1, "First"), (1, "sentence."), (1, "Second"), (2, "one"), (2, "ends."), (2, "Third")]
    assert split_sentences(words) == [(1, "First sentence."), (1, "Second one ends."), (2, "Third")]


def test_windows_respect_size_and_overlap():
    sentences = [(1, sentence(i)) for i in range(100)]
    windows = window_sentences(sentences)
    assert len(windows) > 1
    assert all(len(t.split()) <= CHUNK_WORDS for _, t in windows)
    # The last sentence of one chunk opens the next one
    first_end = windows[0][1].split(". ")[-1]
    assert first_end.rstrip(".") in windows[1][1]


def test_chunks_follow_the_contract():
    chunks = chunk_document(make_doc())
    assert chunks
    for c in chunks:
        Chunk.model_validate(c.model_dump())  # contract 2
        assert c.ticker == "AAPL" and c.fiscal_year == 2019
        assert 0 < len(c.text.split()) <= CHUNK_WORDS + 60
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
    assert ids[0] == "AAPL_2019_10K_p8_c1"


def test_sections_and_content_types():
    chunks = chunk_document(make_doc())
    text = [c for c in chunks if c.content_type == "text"]
    tables = [c for c in chunks if c.content_type == "table"]
    assert {c.section for c in text} >= {"Item 1A"}
    assert len(tables) == 1
    table = tables[0]
    assert table.section == "Item 8" and table.page == 32
    # One table, not cut at the label rows, numbers still under their year
    assert "| Total net sales | 260,174 | 265,595 | 229,234 |" in table.text
    assert "| Net income | 55,256 | 59,531 | 48,351 |" in table.text
    assert "2019 | 2018 | 2017" in table.text


def test_chunking_is_deterministic():
    first = [c.model_dump() for c in chunk_document(make_doc())]
    second = [c.model_dump() for c in chunk_document(make_doc())]
    assert first == second
