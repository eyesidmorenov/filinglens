"""Evaluate BM25, vector, and hybrid retrieval over the FilingLens question set."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from haystack import Document

from . import config
from .retrieval import HybridRetriever

DEFAULT_QUESTIONS = (
    Path(__file__).resolve().parents[1] / "evaluation" / "questions.json"
)


@dataclass(frozen=True)
class EvaluationQuestion:
    id: str
    question: str
    ticker: str
    fiscal_year: int
    category: str
    difficulty: str
    expected_sections: tuple[str, ...]
    relevant_chunk_ids: tuple[str, ...]


def load_questions(path: Path, expected_count: int = 75) -> list[EvaluationQuestion]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise TypeError("evaluation file must contain a JSON list")
    questions = [
        EvaluationQuestion(
            id=item["id"],
            question=item["question"].strip(),
            ticker=item["ticker"].strip().upper(),
            fiscal_year=int(item["fiscal_year"]),
            category=item["category"],
            difficulty=item["difficulty"],
            expected_sections=tuple(item["expected_sections"]),
            relevant_chunk_ids=tuple(item.get("relevant_chunk_ids", [])),
        )
        for item in raw
    ]
    if len(questions) != expected_count:
        raise ValueError(f"expected {expected_count} questions, found {len(questions)}")
    ids = [question.id for question in questions]
    if len(ids) != len(set(ids)):
        raise ValueError("evaluation question ids must be unique")
    for question in questions:
        if not question.question or not question.expected_sections:
            raise ValueError(f"question {question.id} is incomplete")
    return questions


def _rank(documents: Iterable[Document], accepted: set[str], field: str) -> int | None:
    for rank, document in enumerate(documents, start=1):
        value = document.id if field == "id" else (document.meta or {}).get(field)
        if value in accepted:
            return rank
    return None


def _filters_match(question: EvaluationQuestion, documents: Iterable[Document]) -> bool:
    documents = list(documents)
    if not documents:
        return False
    for document in documents:
        meta = document.meta or {}
        if (
            meta.get("ticker") != question.ticker
            or meta.get("fiscal_year") != question.fiscal_year
        ):
            return False
    return True


def _mode_record(
    question: EvaluationQuestion, documents: list[Document]
) -> dict[str, Any]:
    exact_rank = None
    if question.relevant_chunk_ids:
        exact_rank = _rank(documents, set(question.relevant_chunk_ids), "id")
    section_rank = _rank(documents, set(question.expected_sections), "section")
    return {
        "returned_chunk_ids": [document.id for document in documents],
        "result_count": len(documents),
        "filters_match": _filters_match(question, documents),
        "section_rank": section_rank,
        "exact_rank": exact_rank,
    }


def summarize(records: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    mode_records = [
        record["modes"][mode] for record in records if record.get("error") is None
    ]
    total = len(mode_records)
    section_ranks = [record["section_rank"] for record in mode_records]
    exact_records = [
        record["modes"][mode]
        for record in records
        if record.get("error") is None and record["has_exact_labels"]
    ]
    exact_ranks = [record["exact_rank"] for record in exact_records]
    return {
        "questions_completed": total,
        "non_empty_rate": (
            sum(record["result_count"] > 0 for record in mode_records) / total
        )
        if total
        else 0.0,
        "filter_compliance_rate": (
            sum(record["filters_match"] for record in mode_records) / total
        )
        if total
        else 0.0,
        "section_hit_rate_at_k": (
            sum(rank is not None for rank in section_ranks) / total
        )
        if total
        else 0.0,
        "section_mrr_at_k": (
            sum(1 / rank for rank in section_ranks if rank is not None) / total
        )
        if total
        else 0.0,
        "exact_labeled_questions": len(exact_records),
        "exact_hit_rate_at_k": (
            sum(rank is not None for rank in exact_ranks) / len(exact_records)
            if exact_records
            else None
        ),
        "exact_mrr_at_k": (
            sum(1 / rank for rank in exact_ranks if rank is not None)
            / len(exact_records)
            if exact_records
            else None
        ),
    }


def evaluate(
    questions: list[EvaluationQuestion], retriever: HybridRetriever
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for question in questions:
        started = time.perf_counter()
        try:
            result = retriever.run(
                question.question, question.ticker, question.fiscal_year
            )
            records.append(
                {
                    "question": asdict(question),
                    "has_exact_labels": bool(question.relevant_chunk_ids),
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "error": None,
                    "modes": {
                        mode: _mode_record(question, result.documents(mode))
                        for mode in ("bm25", "vector", "hybrid")
                    },
                }
            )
        # A batch report must keep the other questions observable after any one-query failure.
        except Exception as exc:  # noqa: BLE001
            records.append(
                {
                    "question": asdict(question),
                    "has_exact_labels": bool(question.relevant_chunk_ids),
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "error": f"{type(exc).__name__}: {exc}",
                    "modes": {},
                }
            )

    return {
        "settings": {
            "index": config.ES_INDEX,
            "embedding_model": config.EMBEDDING_MODEL,
            "embedding_dimensions": config.EMBEDDING_DIMS,
            "query_prefix": config.QUERY_PREFIX,
            "candidate_top_k": config.CANDIDATE_TOP_K,
            "final_top_k": config.FINAL_TOP_K,
        },
        "question_count": len(questions),
        "error_count": sum(record["error"] is not None for record in records),
        "metrics": {
            mode: summarize(records, mode) for mode in ("bm25", "vector", "hybrid")
        },
        "results": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the FilingLens retrieval question set"
    )
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--expected-count", type=int, default=75)
    parser.add_argument(
        "--output",
        type=Path,
        default=config.data_dir() / "evaluation" / "search-report.json",
    )
    parser.add_argument("--top-k", type=int, default=config.FINAL_TOP_K)
    parser.add_argument("--candidate-top-k", type=int, default=config.CANDIDATE_TOP_K)
    args = parser.parse_args(argv)

    questions = load_questions(args.questions, expected_count=args.expected_count)
    retriever = HybridRetriever.from_settings(
        candidate_top_k=args.candidate_top_k, final_top_k=args.top_k
    )
    report = evaluate(questions, retriever)
    report["settings"]["candidate_top_k"] = args.candidate_top_k
    report["settings"]["final_top_k"] = args.top_k
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))
    print(f"Full report: {args.output}")
    return 1 if report["error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
