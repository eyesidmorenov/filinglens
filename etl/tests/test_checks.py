import pytest

from src import tokens
from src.checks import company_key, known_word_share, names_company, unreadable_pages

PROSE = (
    "We design, manufacture and market smartphones, personal computers, tablets, wearables and accessories, "
    "and sell a variety of related services. The Company's fiscal year is the 52 or 53-week period that ends "
    "on the last Saturday of September. The Company is exposed to risks from changes in the economy, and the "
    "market for its products is highly competitive, with rapid technological change and frequent new products."
)


def shifted(text: str) -> str:
    """Every letter moved one place, as AMD 2019 comes out of its PDF ('currently' -> 'dvssfoumz')."""
    return "".join(chr(ord(c) + 1) if c.isalpha() and c not in "zZ" else c for c in text)


@pytest.fixture(scope="module")
def real_tokenizer():
    try:
        tokens._tokenizer()
    except Exception as e:  # no network and no cached tokenizer
        pytest.skip(f"tokenizer not available: {e}")


def test_english_page_is_readable_and_garbled_page_is_not(real_tokenizer):
    assert known_word_share(PROSE) > 0.7
    assert known_word_share(shifted(PROSE)) < 0.2


def test_pages_with_few_words_are_not_judged(real_tokenizer):
    assert known_word_share("Total net sales | $ 260,174 | $ 265,595") is None


def test_unreadable_pages_counts_only_judged_pages(real_tokenizer):
    assert unreadable_pages([PROSE, shifted(PROSE), "1", PROSE]) == (1, 3)


def test_company_key_drops_generic_words():
    assert company_key("csx-corp") == "csx"
    assert company_key("oreilly-automotive-inc") == "oreilly"
    assert company_key("unknown") is None


def test_cover_with_the_ticker_belongs_to_the_company():
    cover = "Common Stock, $0.001 par value | FB | The Nasdaq Stock Market LLC"
    assert names_company(cover, "FB", "meta-platforms-inc") is True


def test_cover_of_another_company_is_detected():
    # CSX_2020.pdf holds the 10-K of CSW Industrials
    cover = "CSW INDUSTRIALS, INC. (Exact name of registrant as specified in its charter) | CSWI | Nasdaq"
    assert names_company(cover, "CSX", "csx-corp") is False


def test_old_cover_without_ticker_is_matched_by_name():
    # Covers filed before April 2019 have no trading symbol (NVIDIA fiscal 2019)
    assert names_company("NVIDIA CORPORATION (Exact name of registrant)", "NVDA", "nvidia-corporation") is True
    assert names_company("AMAZON.COM, INC. (Exact name of registrant)", "AMZN", "amazoncom-inc") is True


def test_nothing_to_compare_with():
    assert names_company("SOME COMPANY INC. (Exact name of registrant)", "XYZ", "unknown") is None
