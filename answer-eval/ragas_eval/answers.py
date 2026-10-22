"""
Step 1 of 2: answer a sample of the labeled questions with the API's own pipeline.

Runs in the API image (see the ragas-answers service in docker-compose.yml): company and year
detection, hybrid search or Yahoo snapshot, and tenk-answer, exactly as the chat does. For each
question it keeps what RAGAS needs: the question, the answer, its status and the full text of
the chunks Claude was given (the API response only carries short excerpts).

Writes data/eval/ragas/<date and time>/answers.jsonl. Step 2 (score.py) scores that file.

With --testset it answers the questions RAGAS wrote in step 0 (testset.py) instead, in the same run
folder. Those questions don't always name the company or the year, so they go to the pipeline with
the company and year of the filing each one was written from, as the evaluation of the search does.
Their reference answers go into answers.jsonl, for the metrics that compare against them.

Usage (from the repository root; Elasticsearch running and ANTHROPIC_API_KEY in .env):
    docker compose --profile ragas run --rm ragas-answers                        # 30 questions
    docker compose --profile ragas run --rm ragas-answers python -m ragas_eval.answers --limit 5
    docker compose --profile ragas run --rm ragas-answers python -m ragas_eval.answers --limit 0   # all
    docker compose --profile ragas run --rm ragas-answers python -m ragas_eval.answers --testset 2026-10-21_2300
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import DEFAULT_LIMIT, QUESTIONS, load_questions, runs_dir, sample


def answer_one(pipeline: Any, q: dict[str, Any], given_company_year: bool = False) -> dict[str, Any]:
    """Run the API pipeline for one question and keep what RAGAS needs.

    given_company_year: pass the question's own ticker and fiscal year (RAGAS questions) instead of
    detecting them in the text (the labeled questions, which always name both).
    """
    start = time.perf_counter()
    if given_company_year:
        ticker, year, message = pipeline.resolve_company_year(q["question"], q.get("ticker"), q.get("fiscal_year"))
    else:
        ticker, year, message = pipeline.resolve_company_year(q["question"])
    record: dict[str, Any] = {
        "id": q["id"],
        "question": q["question"],
        "category": q.get("category", ""),
        "expected": {"ticker": q.get("ticker"), "fiscal_year": q.get("fiscal_year")},
        "detected": {"ticker": ticker, "fiscal_year": year},
    }
    if message:
        # The API answers this itself, without search or Claude: nothing for RAGAS to score
        record.update(status="not_detected", answer=message, contexts=[], chunk_ids=[], cited=0, usage={})
    else:
        hits = pipeline.retrieve(q["question"], ticker, year)
        result = pipeline.get_generator().run(question=q["question"], documents=hits)
        record.update(
            status=getattr(result.status, "value", str(result.status)),
            answer=result.answer,
            contexts=[h["text"] for h in hits],
            chunk_ids=[h["chunk_id"] for h in hits],
            cited=len(result.sources),
            usage=dict(result.usage or {}),
        )
    if q.get("reference"):
        record["reference"] = q["reference"]
    record["latency_ms"] = round((time.perf_counter() - start) * 1000)
    return record


def failed(q: dict[str, Any], exc: Exception) -> dict[str, Any]:
    """A question that raised: kept in the file, so one failure does not lose the whole run."""
    return {
        "id": q["id"], "question": q["question"], "category": q.get("category", ""),
        "expected": {"ticker": q.get("ticker"), "fiscal_year": q.get("fiscal_year")}, "detected": {},
        "status": "error", "answer": f"{type(exc).__name__}: {exc}", "contexts": [], "chunk_ids": [],
        "cited": 0, "usage": {}, "latency_ms": 0,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Step 1: answer labeled questions with the API pipeline")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                    help=f"number of questions, spread over the categories (default {DEFAULT_LIMIT}; 0 = all)")
    ap.add_argument("--questions", type=Path, default=QUESTIONS, help="labeled questions (search/evaluation)")
    ap.add_argument("--out", type=Path, default=None, help="run folder (default: data/eval/ragas/<time>)")
    ap.add_argument("--testset", default=None,
                    help="answer the RAGAS questions of this run (folder name under data/eval/ragas, from step 0)")
    args = ap.parse_args(argv)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is not set: put it in the .env at the repository root", file=sys.stderr)
        return 1

    from app import pipeline  # the API's own pipeline (api/app/pipeline.py)

    if args.testset:
        out_dir = runs_dir() / args.testset
        with open(out_dir / "testset.jsonl", encoding="utf-8") as f:
            chosen = [json.loads(line) for line in f if line.strip()]
        chosen = [q for q in chosen if q.get("ticker") and q.get("fiscal_year")]
    else:
        chosen = sample(load_questions(args.questions), args.limit)
        out_dir = args.out or runs_dir() / datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "answers.jsonl"
    print(f"Answering {len(chosen)} questions with the API pipeline -> {path}")

    statuses: dict[str, int] = {}
    with open(path, "w", encoding="utf-8") as f:
        for i, q in enumerate(chosen, 1):
            try:
                record = answer_one(pipeline, q, given_company_year=bool(args.testset))
            except Exception as exc:
                record = failed(q, exc)
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()  # what is answered is kept even if the run stops
            statuses[record["status"]] = statuses.get(record["status"], 0) + 1
            print(f"  [{i:>3}/{len(chosen)}] {record['id']:<5} {record['status']:<20} {record['latency_ms']:>6} ms")
            if i == 3 and statuses.get("error") == 3:
                # Elasticsearch down, no index or a bad key: stop instead of failing every question
                print(f"\nERROR: the first 3 questions failed; stopping. Last error: {record['answer']}",
                      file=sys.stderr)
                return 1

    print(f"\nStatus: {dict(sorted(statuses.items()))}")
    print("Next: docker compose --profile ragas run --rm ragas   (scores the latest run)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
