"""What both steps share: where the questions and the runs live, and which questions are used."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[2]  # the repository root (or /app in Docker)
QUESTIONS = Path(os.environ.get("QUESTIONS_FILE", HERE / "search" / "evaluation" / "questions.json"))
DEFAULT_LIMIT = 30


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", HERE / "data"))


def runs_dir() -> Path:
    """data/eval/ragas: one folder per run, named by its date and time (UTC)."""
    return data_dir() / "eval" / "ragas"


def load_questions(path: Path = QUESTIONS) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["questions"] if isinstance(data, dict) else data


def sample(questions: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """`limit` questions spread over every category, always the same ones (no randomness).

    Takes one question per category in turn, in file order, so 30 of the 150 keep every
    category and two runs score the same questions. limit 0 (or more than all) = all.
    """
    if limit <= 0 or limit >= len(questions):
        return list(questions)
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for q in questions:
        by_category[q.get("category", "")].append(q)
    queues = [list(qs) for _, qs in sorted(by_category.items())]
    chosen: list[dict[str, Any]] = []
    while len(chosen) < limit:
        for queue in queues:
            if queue and len(chosen) < limit:
                chosen.append(queue.pop(0))
    order = {q["id"]: i for i, q in enumerate(questions)}
    return sorted(chosen, key=lambda q: order[q["id"]])


def latest_run() -> Path | None:
    """The newest run folder that has an answers.jsonl, or None."""
    runs = sorted(p for p in runs_dir().glob("*") if (p / "answers.jsonl").is_file()) if runs_dir().exists() else []
    return runs[-1] if runs else None
