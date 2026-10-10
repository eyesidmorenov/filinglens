from haystack import Document
from haystack.components.joiners import DocumentJoiner
from src.retrieval import HybridRetriever


def _doc(identifier, score, section="Item 1A"):
    return Document(
        id=identifier,
        content=f"text {identifier}",
        score=score,
        meta={
            "ticker": "AAPL",
            "fiscal_year": 2019,
            "section": section,
            "page": 1,
            "company": "apple-inc",
        },
    )


class FakeEmbedder:
    def __init__(self):
        self.text = None

    def run(self, *, text):
        self.text = text
        return {"embedding": [0.1, 0.2]}


class FakeBM25:
    def __init__(self, documents):
        self.documents = documents
        self.call = None

    def run(self, **kwargs):
        self.call = kwargs
        return {"documents": self.documents}


class FakeVector(FakeBM25):
    pass


class FakeJoiner:
    def __init__(self, output):
        self.output = output
        self.documents = None

    def run(self, *, documents):
        self.documents = documents
        return {"documents": self.output}


def test_hybrid_search_uses_one_question_and_identical_filters():
    bm25_docs = [_doc("lexical", 2.0), _doc("both", 1.0)]
    vector_docs = [_doc("both", 0.9), _doc("semantic", 0.8)]
    fused_docs = [_doc("both", 0.03), _doc("lexical", 0.02)]
    embedder = FakeEmbedder()
    bm25 = FakeBM25(bm25_docs)
    vector = FakeVector(vector_docs)
    joiner = FakeJoiner(fused_docs)
    retriever = HybridRetriever(
        text_embedder=embedder,
        bm25_retriever=bm25,
        vector_retriever=vector,
        joiner=joiner,
        final_top_k=2,
    )

    result = retriever.run("  What are Apple's risks?  ", "aapl", 2019)

    assert embedder.text == "What are Apple's risks?"
    assert bm25.call["query"] == embedder.text
    assert bm25.call["filters"] == vector.call["filters"]
    assert vector.call["query_embedding"] == [0.1, 0.2]
    assert joiner.documents == [bm25_docs, vector_docs]
    assert result.bm25 == bm25_docs
    assert result.vector == vector_docs
    assert result.hybrid == fused_docs


def test_all_modes_are_returned_at_the_same_final_top_k():
    documents = [_doc(str(i), 1.0 / (i + 1)) for i in range(4)]
    retriever = HybridRetriever(
        text_embedder=FakeEmbedder(),
        bm25_retriever=FakeBM25(documents),
        vector_retriever=FakeVector(documents),
        joiner=FakeJoiner(documents),
        final_top_k=2,
    )
    result = retriever.run("question", "AAPL", 2019)
    assert len(result.bm25) == len(result.vector) == len(result.hybrid) == 2


def test_haystack_rrf_promotes_a_document_found_by_both_retrievers():
    bm25_docs = [_doc("lexical", 2.0), _doc("both", 1.0)]
    vector_docs = [_doc("both", 0.9), _doc("semantic", 0.8)]
    fused = DocumentJoiner(join_mode="reciprocal_rank_fusion", top_k=3).run(
        documents=[bm25_docs, vector_docs]
    )["documents"]
    assert [document.id for document in fused] == ["both", "lexical", "semantic"]
