from src.chunk import (
    chunk_document,
    looks_like_table_header,
    split_long_sentence,
    split_sentences,
    window_sentences,
)
from src.models import Chunk, Document, Page
from src.tokens import CHUNK_MAX_TOKENS, CHUNK_TARGET_TOKENS, OVERLAP_TOKENS

META = dict(
    doc_id="AAPL_2019_10K", company="apple-inc", ticker="AAPL", fiscal_year=2019,
    exchange="NASDAQ", s3_key="nasdaq_annual_reports/apple-inc/NASDAQ_AAPL_2019.pdf",
    local_path="data/raw/AAPL_2019.pdf", size_mb=5.25, n_pages=40, doc_type="10-K",
    form_10k_pages=(1, 40),
)


def words(text: str) -> int:
    """Test counter: one token per word, so sizes are easy to reason about."""
    return len(text.split())


def sentence(i: int) -> str:
    return f"This is risk sentence number {i} about supply chains and demand."


def make_doc(prose: str | None = None) -> Document:
    risk = prose or "\n".join(sentence(i) for i in range(120))  # ~1,300 words
    statement = "\n".join([
        "The following table shows our results as a percentage of revenue.",
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
    ws = [(1, "First"), (1, "sentence."), (1, "Second"), (2, "one"), (2, "ends."), (2, "Third")]
    assert split_sentences(ws) == [(1, "First sentence."), (1, "Second one ends."), (2, "Third")]


def test_windows_respect_target_and_overlap():
    sentences = [(1, sentence(i)) for i in range(200)]
    windows = window_sentences(sentences, words)
    assert len(windows) > 1
    assert all(words(t) <= CHUNK_TARGET_TOKENS for _, t in windows)
    # The last sentence of one chunk is repeated at the start of the next one
    last = windows[0][1].split(". ")[-1]
    assert last in windows[1][1][: len(windows[0][1]) // 2]


def test_overlap_never_pushes_a_chunk_past_the_cap():
    # Regression: a full overlap tail followed by a sentence as long as the target
    # used to produce chunks of target + overlap.
    short = [(1, " ".join(["word"] * 10) + ".") for _ in range(OVERLAP_TOKENS // 10 + 40)]
    long_one = [(2, " ".join(["long"] * (CHUNK_MAX_TOKENS - 20)) + ".")]
    windows = window_sentences(short + long_one + short, words)
    assert max(words(t) for _, t in windows) <= CHUNK_MAX_TOKENS


def test_long_sentence_is_split_with_overlap_and_within_target():
    text = " ".join(f"w{i}" for i in range(1000))
    pieces = split_long_sentence(3, text, words)
    assert len(pieces) > 2
    assert all(words(p) <= CHUNK_TARGET_TOKENS for _, p in pieces)
    assert all(page == 3 for page, _ in pieces)
    # Consecutive pieces share their border words and cover the whole sentence
    assert pieces[0][1].split()[-1] in pieces[1][1].split()
    assert pieces[-1][1].split()[-1] == "w999"


def test_table_header_rule():
    assert looks_like_table_header("CONSOLIDATED STATEMENTS OF OPERATIONS")
    assert looks_like_table_header("Years ended")
    assert looks_like_table_header("Net sales:")
    assert looks_like_table_header("(In millions, except per share amounts)")
    assert looks_like_table_header("2019 | 2018 | 2017")
    assert not looks_like_table_header("as a percentage of revenue.")
    assert not looks_like_table_header("The following table shows our results as a percentage of revenue.")


def test_chunks_follow_the_contract():
    chunks = chunk_document(make_doc(), count=words)
    assert chunks
    for c in chunks:
        Chunk.model_validate(c.model_dump())  # contract 2
        assert c.ticker == "AAPL" and c.fiscal_year == 2019
        assert 0 < words(c.text) <= CHUNK_MAX_TOKENS
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
    assert ids[0] == "AAPL_2019_10K_p8_c1"


def test_sections_and_content_types():
    chunks = chunk_document(make_doc(), count=words)
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
    assert "CONSOLIDATED STATEMENTS OF OPERATIONS" in table.text


def test_table_does_not_steal_the_end_of_the_paragraph():
    chunks = chunk_document(make_doc(), count=words)
    table = next(c for c in chunks if c.content_type == "table")
    assert "percentage of revenue" not in table.text
    assert any("percentage of revenue" in c.text for c in chunks if c.content_type == "text")


def test_long_table_is_split_repeating_its_header():
    rows = "\n".join(f"Line item {i} | {i},000 | {i},100 | {i},200" for i in range(200))
    doc = Document(**META, pages=[Page(page=40, text="Item 8. Financial Statements\nSEGMENTS\n2019 | 2018 | 2017\n" + rows)])
    tables = [c for c in chunk_document(doc, count=words) if c.content_type == "table"]
    assert len(tables) > 1
    assert all("2019 | 2018 | 2017" in t.text and words(t.text) <= CHUNK_MAX_TOKENS for t in tables)


def test_chunking_is_deterministic():
    first = [c.model_dump() for c in chunk_document(make_doc(), count=words)]
    second = [c.model_dump() for c in chunk_document(make_doc(), count=words)]
    assert first == second
