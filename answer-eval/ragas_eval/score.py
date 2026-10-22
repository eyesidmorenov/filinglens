"""
Step 2: score the answers of step 1 with RAGAS.

    context_recall       the chunks given to Claude hold everything the reference answer needs (search)
    context_precision    the useful chunks come first (search)
    faithfulness         every claim in the answer is supported by those chunks: no hallucination
    answer_relevancy     the answer addresses the question that was asked
    factual_correctness  the answer agrees with the reference answer

All from 0 to 1. The questions RAGAS wrote in step 0 have a reference answer, so they get the five
metrics of Mariano's script. The labeled questions have none: they get the three that don't need
it (faithfulness, answer_relevancy and context_precision without a reference).

The judge is Claude (claude-sonnet-5 unless RAGAS_MODEL or --model says otherwise) and the
embeddings for answer_relevancy are the BGE model the index already uses, so no OpenAI key is
needed. Only answers with status "answered" are scored: a refusal or an "I don't know" has no
claims to check; they are counted apart, by status.

Runs in its own image (answer-eval/Dockerfile): RAGAS needs other versions of the Anthropic and
LangChain libraries than tenk-answer, so the two steps never share an environment.

Reads data/eval/ragas/<run>/answers.jsonl (the latest run by default) and writes, in the same folder:
    scores.csv      one row per scored answer with its scores (five, or three without a reference)
    summary.json    averages, by category, status counts, tokens and the judge model

Usage (from the repository root):
    docker compose --profile ragas run --rm ragas
    docker compose --profile ragas run --rm ragas python -m ragas_eval.score --run data/eval/ragas/2026-10-21_1700
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from .common import latest_run, ragas_models

METRICS_WITHOUT_REFERENCE = ("faithfulness", "answer_relevancy", "context_precision")
METRICS_WITH_REFERENCE = ("context_recall", "context_precision", "faithfulness", "answer_relevancy",
                          "factual_correctness")
METRICS = METRICS_WITH_REFERENCE  # every metric a run can have, in the order they are shown


def metric_columns(scored: list[dict[str, Any]]) -> tuple[str, ...]:
    """The metrics of a run: the five with reference answers, else the three without."""
    with_reference = any(r.get(m) is not None for r in scored for m in ("context_recall", "factual_correctness"))
    return METRICS_WITH_REFERENCE if with_reference else METRICS_WITHOUT_REFERENCE


def our_name(ragas_column: str) -> str | None:
    """RAGAS result column -> our metric name: "factual_correctness(mode=f1)" -> "factual_correctness"."""
    if ragas_column.startswith("llm_context_precision"):
        return "context_precision"
    for name in METRICS:
        if ragas_column == name or ragas_column.startswith(name + "("):
            return name
    return None


def load_answers(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def to_score(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The records RAGAS can score: answered, with chunks."""
    return [r for r in records if r.get("status") == "answered" and r.get("contexts")]


def judge(model: str):
    """RAGAS judge (Claude, without `temperature`) and embeddings (BGE): see common.ragas_models."""
    return ragas_models(model)


def ragas_scores(records: list[dict[str, Any]], model: str) -> tuple[list[dict[str, float | None]], dict[str, int]]:
    """The scores of each record, in the same order (five with reference answers, three without),
    and the tokens the judge used."""
    from ragas import EvaluationDataset, RunConfig, evaluate
    from ragas.cost import get_token_usage_for_anthropic
    from ragas.metrics import (
        FactualCorrectness,
        Faithfulness,
        LLMContextPrecisionWithoutReference,
        LLMContextPrecisionWithReference,
        LLMContextRecall,
        ResponseRelevancy,
    )

    llm, embeddings = judge(model)
    with_reference = all(r.get("reference") for r in records)
    rows = []
    for r in records:
        row = {"user_input": r["question"], "response": r["answer"], "retrieved_contexts": r["contexts"]}
        if with_reference:
            row["reference"] = r["reference"]
        rows.append(row)
    if with_reference:
        metrics = [
            LLMContextRecall(llm=llm),
            LLMContextPrecisionWithReference(llm=llm),
            Faithfulness(llm=llm),
            ResponseRelevancy(llm=llm, embeddings=embeddings),
            FactualCorrectness(llm=llm),
        ]
    else:
        metrics = [
            Faithfulness(llm=llm),
            ResponseRelevancy(llm=llm, embeddings=embeddings),
            LLMContextPrecisionWithoutReference(llm=llm),
        ]
    result = evaluate(
        EvaluationDataset.from_list(rows),
        metrics=metrics,
        run_config=RunConfig(max_workers=4, timeout=180),
        show_progress=True,
        token_usage_parser=get_token_usage_for_anthropic,
    )
    frame = result.to_pandas()
    columns = {c: our_name(c) for c in frame.columns if our_name(c)}
    try:
        usage = result.total_tokens()
        tokens = {"input": int(usage.input_tokens), "output": int(usage.output_tokens)}
    except Exception:  # noqa: BLE001 - the token count is a nice-to-have
        tokens = {}
    scores = [{ours: clean(row.get(theirs)) for theirs, ours in columns.items()} for _, row in frame.iterrows()]
    return scores, tokens


def clean(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else round(number, 4)  # NaN (a failed judge call) -> None


def summarize(records: list[dict[str, Any]], scored: list[dict[str, Any]]) -> dict[str, Any]:
    """Averages over the scored answers, by category, and every question's status."""
    present = metric_columns(scored)

    def averages(rows: list[dict[str, Any]]) -> dict[str, float | None]:
        out = {}
        for metric in present:
            values = [r[metric] for r in rows if r.get(metric) is not None]
            out[metric] = round(mean(values), 3) if values else None
        return out

    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scored:
        by_category[row["category"]].append(row)
    statuses: dict[str, int] = defaultdict(int)
    for r in records:
        statuses[r.get("status", "")] += 1
    latencies = sorted(r.get("latency_ms", 0) for r in records if r.get("status") == "answered")
    return {
        "questions": len(records),
        "scored": len(scored),
        "status": dict(sorted(statuses.items())),
        "company_and_year_detected_as_labeled": sum(r.get("detected") == r.get("expected") for r in records),
        "average": averages(scored),
        "by_category": {c: {"n": len(rows), **averages(rows)} for c, rows in sorted(by_category.items())},
        "answer_tokens": {
            "input": sum((r.get("usage") or {}).get("input_tokens", 0) for r in records),
            "output": sum((r.get("usage") or {}).get("output_tokens", 0) for r in records),
        },
        "median_latency_ms_answered": latencies[len(latencies) // 2] if latencies else None,
    }


def write_outputs(run: Path, scored: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    with open(run / "scores.csv", "w", encoding="utf-8", newline="") as f:
        present = metric_columns(scored)
        writer = csv.DictWriter(f, fieldnames=["id", "category", *present, "question"])
        writer.writeheader()
        for row in scored:
            writer.writerow({k: row.get(k) for k in writer.fieldnames})
    with open(run / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)


def print_summary(summary: dict[str, Any]) -> None:
    print(f"\n{summary['scored']} of {summary['questions']} questions scored; status: {summary['status']}")
    present = list(summary["average"])
    for metric in present:
        value = summary["average"].get(metric)
        print(f"  {metric:<20} {value if value is not None else 'n/a'}")
    print("\nBy category:")
    for category, row in summary["by_category"].items():
        values = "  ".join(f"{m} {row[m] if row[m] is not None else 'n/a'}" for m in present)
        print(f"  {category:<22} n={row['n']:<3} {values}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Step 2: score the answers of step 1 with RAGAS")
    ap.add_argument("--run", type=Path, default=None, help="run folder from step 1 (default: the latest)")
    ap.add_argument("--model", default=os.environ.get("RAGAS_MODEL", "claude-sonnet-5"),
                    help="Claude model used as the RAGAS judge")
    args = ap.parse_args(argv)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is not set: put it in the .env at the repository root", file=sys.stderr)
        return 1
    run = args.run or latest_run()
    if run is None or not (run / "answers.jsonl").is_file():
        print("ERROR: no answers to score: run step 1 first "
              "(docker compose --profile ragas run --rm ragas-answers)", file=sys.stderr)
        return 1

    records = load_answers(run / "answers.jsonl")
    answered = to_score(records)
    print(f"Scoring {len(answered)} of {len(records)} answers in {run} (judge: {args.model})")
    scores, judge_tokens = ragas_scores(answered, args.model) if answered else ([], {})
    scored = [{"id": r["id"], "category": r.get("category", ""), "question": r["question"], **s}
              for r, s in zip(answered, scores)]

    summary = summarize(records, scored)
    summary["judge_model"] = args.model
    summary["judge_tokens"] = judge_tokens
    summary["run"] = run.name
    write_outputs(run, scored, summary)
    print_summary(summary)
    print(f"\nWritten: {run}/summary.json and scores.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
