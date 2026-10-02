"""The real BGE tokenizer. Skipped when it can't be downloaded (offline)."""

import pytest

from src import tokens


@pytest.fixture(scope="module")
def real_tokenizer():
    try:
        tokens._tokenizer()
    except Exception as e:  # no network and no cached tokenizer
        pytest.skip(f"tokenizer not available: {e}")


def test_sum_of_words_equals_tokenizing_the_whole_text(real_tokenizer):
    text = "Apple's net sales were $260,174 million in fiscal 2019 (U.S. and international)."
    whole = len(tokens._tokenizer().encode(text, add_special_tokens=False).ids)
    assert tokens.count_tokens(text) == whole


def test_budget_leaves_room_for_the_context_header():
    # header (~30 tokens) + chunk + 2 special tokens must fit the model
    assert tokens.CHUNK_MAX_TOKENS + 2 + 40 <= tokens.MODEL_MAX_TOKENS
    assert tokens.OVERLAP_TOKENS < tokens.CHUNK_TARGET_TOKENS <= tokens.CHUNK_MAX_TOKENS
