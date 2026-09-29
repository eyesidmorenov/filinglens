from __future__ import annotations

from typing import Any

from haystack import Document, Pipeline, component
from helpers import FakeChatGenerator, tool_reply

from tenk_answer import Answer, AnswerComponent, AnswerGenerator, AnswerStatus, SearchResult


@component
class FakeRetriever:
    def __init__(self, documents: list[Document]) -> None:
        self.documents = documents

    @component.output_types(documents=list[Document])
    def run(self, query: str) -> dict[str, list[Document]]:
        return {"documents": self.documents}


def test_component_runs_in_pipeline_after_retriever(results: dict[str, SearchResult]) -> None:
    docs = [results["AAPL_2024_10K_p21_c1"].to_document(), results["AAPL_2023_10K_p20_c1"].to_document()]
    fake = FakeChatGenerator(tool_reply(sources=[{"doc_id": "D1", "excerpt": "$391,035 million"}]))

    pipe = Pipeline()
    pipe.add_component("retriever", FakeRetriever(docs))
    pipe.add_component("answer", AnswerComponent(AnswerGenerator(generator=fake)))
    pipe.connect("retriever.documents", "answer.documents")

    question = "What were Apple's FY2024 net sales?"
    out: dict[str, Any] = pipe.run({"retriever": {"query": question}, "answer": {"question": question}})

    answer = out["answer"]["answer"]
    assert isinstance(answer, Answer)
    assert answer.status is AnswerStatus.ANSWERED
    assert answer.sources[0].chunk_id == "AAPL_2024_10K_p21_c1"
    assert answer.sources[0].fiscal_year == 2024
    assert len(fake.calls) == 1


def test_component_standalone_empty_documents() -> None:
    fake = FakeChatGenerator()
    out = AnswerComponent(AnswerGenerator(generator=fake)).run(question="q", documents=[])
    assert out["answer"].status is AnswerStatus.INSUFFICIENT_CONTEXT
    assert fake.calls == []
