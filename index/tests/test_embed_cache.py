"""The embedding cache, with a fake embedder: no model download needed."""

import numpy as np
import pytest
from haystack import Document

from src import config, load
from src.documents import chunk_to_document

BASE = {"doc_id": "AAPL_2019_10K", "section": "Item 1A", "page": 8, "company": "apple-inc",
        "ticker": "AAPL", "fiscal_year": 2019, "content_type": "text", "doc_type": "10-K"}


class FakeEmbedder:
    def __init__(self):
        self.embedded: list[str] = []

    def run(self, documents):
        self.embedded.extend(d.content for d in documents)
        out = []
        for d in documents:
            v = np.random.default_rng(abs(hash(d.content)) % 2**32).random(config.EMBEDDING_DIMS)
            out.append(Document(id=d.id, content=d.content, embedding=(v / np.linalg.norm(v)).tolist()))
        return {"documents": out}


@pytest.fixture
def fake(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    embedder = FakeEmbedder()
    monkeypatch.setattr(load, "embedder", lambda: embedder)
    return embedder


def docs(*texts: str) -> list[Document]:
    return [chunk_to_document({**BASE, "chunk_id": f"AAPL_2019_10K_p8_c{i}", "text": t})
            for i, t in enumerate(texts, start=1)]


def test_first_run_embeds_everything_with_the_context_header(fake):
    out, computed = load.embed(docs("Supply may fail.", "Demand may drop."), "AAPL_2019_10K")
    assert computed == 2
    assert all(len(d.embedding) == config.EMBEDDING_DIMS for d in out)
    assert fake.embedded[0].startswith("Apple Inc (AAPL) | Fiscal 2019 | Item 1A Risk Factors\n")
    assert out[0].content == "Supply may fail."  # stored content has no header


def test_second_run_uses_the_cache(fake):
    load.embed(docs("Supply may fail.", "Demand may drop."), "AAPL_2019_10K")
    _, computed = load.embed(docs("Supply may fail.", "Demand may drop."), "AAPL_2019_10K")
    assert computed == 0


def test_changed_text_with_the_same_id_is_embedded_again(fake):
    # Regression: the cache used to be keyed by chunk ids only
    first, _ = load.embed(docs("Supply may fail.", "Demand may drop."), "AAPL_2019_10K")
    second, computed = load.embed(docs("Supply may fail.", "Demand may drop sharply."), "AAPL_2019_10K")
    assert computed == 1
    assert second[0].embedding == first[0].embedding
    assert second[1].embedding != first[1].embedding


def test_broken_cache_is_ignored(fake):
    load.embed(docs("Supply may fail."), "AAPL_2019_10K")
    load.cache_path("AAPL_2019_10K").write_bytes(b"not a numpy file")
    _, computed = load.embed(docs("Supply may fail."), "AAPL_2019_10K")
    assert computed == 1
