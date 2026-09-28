"""Haystack component wrapper so the generator can sit right after the retriever in a pipeline."""

from __future__ import annotations

from haystack import Document, component

from tenk_answer.generator import AnswerGenerator
from tenk_answer.types import Answer


@component
class AnswerComponent:
    def __init__(self, answer_generator: AnswerGenerator) -> None:
        self.answer_generator = answer_generator

    @component.output_types(answer=Answer)
    def run(self, question: str, documents: list[Document]) -> dict[str, Answer]:
        return {"answer": self.answer_generator.run(question=question, documents=documents)}
