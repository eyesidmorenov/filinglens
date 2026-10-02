"""
Token counting with the embedding model's own tokenizer.

Chunks are sized in tokens, not words, so none of them gets silently truncated
by BGE (512 tokens). BGE v1.5 small, base and large share the same WordPiece
vocabulary, so the count does not depend on which size the team picks.

WordPiece splits text on whitespace before anything else, so the token count of
a text equals the sum of the counts of its words. Words are counted once and
cached.
"""

import os
from functools import lru_cache

TOKENIZER_MODEL = os.environ.get("TOKENIZER_MODEL", "BAAI/bge-base-en-v1.5")

# Budget per chunk. The index adds a context header before embedding
# ("Apple Inc (AAPL) | Fiscal 2019 | Item 1A Risk Factors") and the model adds
# two special tokens, so chunks stay well below the 512-token limit.
MODEL_MAX_TOKENS = 512
CHUNK_MAX_TOKENS = 440   # hard cap, never exceeded
CHUNK_TARGET_TOKENS = 380  # a chunk closes when the next sentence would pass this
OVERLAP_TOKENS = 50


@lru_cache(maxsize=1)
def _tokenizer():
    from tokenizers import Tokenizer

    return Tokenizer.from_pretrained(TOKENIZER_MODEL)


@lru_cache(maxsize=200_000)
def word_tokens(word: str) -> int:
    return len(_tokenizer().encode(word, add_special_tokens=False).ids)


def count_tokens(text: str) -> int:
    """Tokens of `text` without special tokens, as BGE counts them."""
    return sum(word_tokens(w) for w in text.split())
