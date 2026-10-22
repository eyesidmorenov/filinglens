"""
Step 0: RAGAS writes the test questions, with their reference answers, from our own documents.

This is the first half of Mariano's eval_ragas.py: "load your documents and generate a test set
(with a reference answer) from them". Our documents are the chunks the ETL already wrote
(data/chunks/<doc_id>.jsonl): the same 10-K text the index holds, already cleaned, and each one
knows its company and fiscal year.

RAGAS reads a few chunks of each chosen filing, builds its knowledge graph (summaries, themes and
named entities, written by Claude) and writes single-hop questions: each one is answered by one
chunk, so we know the company and year it is about. A question that mixed two filings could not
be answered: the chat filters by company and year, and comparisons are out of scope.

Writes data/eval/ragas/<date and time>/testset.jsonl (and testset.csv to read and review by hand,
as Mariano suggests). Step 1 (answers.py --testset) answers it; step 2 (score.py) scores it.

Usage (from the repository root; ANTHROPIC_API_KEY in .env):
    docker compose --profile ragas run --rm ragas python -m ragas_eval.testset --n 2 --filings 1   # cost check
    docker compose --profile ragas run --rm ragas python -m ragas_eval.testset                     # 20 questions
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import data_dir, runs_dir

DEFAULT_N = 20
DEFAULT_FILINGS = 10
CHUNKS_PER_FILING = 8
# The sections an analyst asks about. The cover, the contents and the exhibits list say little.
SECTIONS = ("Item 1", "Item 1A", "Item 3", "Item 7", "Item 7A", "Item 8", "Item 9A")
MIN_WORDS = 80  # a chunk too short gives a question about almost nothing

# Who asks the questions: our user (slide "Who it is for")
PERSONA_NAME = "Equity analyst"
PERSONA_ROLE = (
    "An investor doing fundamental analysis of a NASDAQ company. Before deciding on their own, they "
    "read the company's annual 10-K report to check revenue, profit, debt, risks and strategy, and "
    "always want to know where each figure comes from."
)


def read_chunks(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def pick_filings(doc_ids: list[str], count: int) -> list[str]:
    """`count` filings of different companies, evenly spread, years taking turns (no randomness)."""
    by_company: dict[str, list[str]] = {}
    for doc_id in sorted(doc_ids):
        by_company.setdefault(doc_id.split("_")[0], []).append(doc_id)
    companies = sorted(by_company)
    if count >= len(companies):
        chosen = companies
    else:
        step = len(companies) / count
        chosen = [companies[int(i * step)] for i in range(count)]
    return [by_company[c][i % len(by_company[c])] for i, c in enumerate(chosen)]


def pick_chunks(chunks: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """`count` chunks spread over the filing's key sections, prose and tables, in reading order."""
    eligible = [c for c in chunks if c.get("section") in SECTIONS and len(c["text"].split()) >= MIN_WORDS]
    if len(eligible) <= count:
        return eligible
    step = len(eligible) / count
    return [eligible[int(i * step)] for i in range(count)]


def documents(filings: list[str], chunks_dir: Path, per_filing: int) -> list[Any]:
    """The chosen chunks as LangChain documents, each with its company, year, section and page."""
    from langchain_core.documents import Document

    docs = []
    for doc_id in filings:
        for chunk in pick_chunks(read_chunks(chunks_dir / f"{doc_id}.jsonl"), per_filing):
            docs.append(Document(
                page_content=chunk["text"],
                metadata={k: chunk.get(k) for k in ("chunk_id", "doc_id", "ticker", "fiscal_year", "section", "page",
                                                     "company", "company_name")},
            ))
    return docs


def source_of(reference_contexts: list[str], docs: list[Any]) -> dict[str, Any]:
    """The chunk a single-hop question was written from: same text, or the one that contains it."""
    for context in reference_contexts or []:
        for doc in docs:
            if context.strip() and (context.strip() == doc.page_content.strip() or context.strip() in doc.page_content):
                return doc.metadata
    return {}


def judge(model: str):
    """Claude (through LangChain) for RAGAS, and the BGE embeddings the index already uses."""
    from langchain_anthropic import ChatAnthropic
    from langchain_huggingface import HuggingFaceEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper

    llm = LangchainLLMWrapper(ChatAnthropic(model=model, max_tokens=4096, timeout=120, max_retries=3))
    embeddings = LangchainEmbeddingsWrapper(
        HuggingFaceEmbeddings(model_name=os.environ.get("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5"))
    )
    return llm, embeddings


def generate(docs: list[Any], n: int, model: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """RAGAS test set: question, reference answer and reference contexts, plus the tokens used."""
    from ragas import RunConfig
    from ragas.cost import get_token_usage_for_anthropic
    from ragas.testset import TestsetGenerator
    from ragas.testset.persona import Persona
    from ragas.testset.synthesizers.single_hop.specific import SingleHopSpecificQuerySynthesizer

    llm, embeddings = judge(model)
    generator = TestsetGenerator(
        llm=llm, embedding_model=embeddings,
        persona_list=[Persona(name=PERSONA_NAME, role_description=PERSONA_ROLE)],
    )
    testset = generator.generate_with_langchain_docs(
        docs,
        testset_size=n,
        query_distribution=[(SingleHopSpecificQuerySynthesizer(llm=llm), 1.0)],
        run_config=RunConfig(max_workers=4, timeout=180),
        token_usage_parser=get_token_usage_for_anthropic,
    )
    rows = testset.to_pandas().to_dict("records")
    try:
        usage = testset.total_tokens()
        tokens = {"input": int(usage.input_tokens), "output": int(usage.output_tokens)}
    except Exception:  # noqa: BLE001 - the token count is a nice-to-have
        tokens = {}
    return rows, tokens


def to_questions(rows: list[dict[str, Any]], docs: list[Any]) -> list[dict[str, Any]]:
    """Our question records: RAGAS fields plus the filing each question is about."""
    questions = []
    for i, row in enumerate(rows, 1):
        meta = source_of(list(row.get("reference_contexts") or []), docs)
        questions.append({
            "id": f"G{i:02d}",
            "question": row["user_input"],
            "reference": row.get("reference", ""),
            "reference_contexts": list(row.get("reference_contexts") or []),
            "synthesizer": row.get("synthesizer_name", ""),
            "ticker": meta.get("ticker"),
            "fiscal_year": meta.get("fiscal_year"),
            "category": meta.get("section") or "",  # the section of the source chunk
            "source_chunk_id": meta.get("chunk_id"),
            "company_name": meta.get("company_name"),
        })
    return questions


def write(run: Path, questions: list[dict[str, Any]], info: dict[str, Any]) -> None:
    run.mkdir(parents=True, exist_ok=True)
    with open(run / "testset.jsonl", "w", encoding="utf-8") as f:
        for q in questions:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    with open(run / "testset.csv", "w", encoding="utf-8", newline="") as f:
        fields = ["id", "ticker", "fiscal_year", "category", "question", "reference"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: q.get(k) for k in fields} for q in questions)
    with open(run / "testset_info.json", "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Step 0: RAGAS writes test questions from our documents")
    ap.add_argument("--n", type=int, default=DEFAULT_N, help=f"questions to generate (default {DEFAULT_N})")
    ap.add_argument("--filings", type=int, default=DEFAULT_FILINGS,
                    help=f"how many filings to read, of different companies (default {DEFAULT_FILINGS})")
    ap.add_argument("--chunks-per-filing", type=int, default=CHUNKS_PER_FILING)
    ap.add_argument("--doc", action="append", default=[], help="a filing to use (repeatable), e.g. AAPL_2020_10K")
    ap.add_argument("--only", type=Path, default=None,
                    help="limit the companies to the tickers of this questions file (default: the 50 of the "
                         "evaluation set, the v5 package delivered on Friday)")
    ap.add_argument("--model", default=os.environ.get("RAGAS_MODEL", "claude-sonnet-5"),
                    help="Claude model that writes the questions")
    args = ap.parse_args(argv)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is not set: put it in the .env at the repository root", file=sys.stderr)
        return 1
    chunks_dir = data_dir() / "chunks"
    available = sorted(p.stem for p in chunks_dir.glob("*_10K.jsonl"))
    if not available:
        print(f"ERROR: no chunks in {chunks_dir}: load the chunk package first", file=sys.stderr)
        return 1
    only = args.only or Path(os.environ.get("QUESTIONS_FILE", ""))
    if only.is_file():
        with open(only, encoding="utf-8") as f:
            data = json.load(f)
        tickers = {q["ticker"] for q in (data["questions"] if isinstance(data, dict) else data)}
        available = [d for d in available if d.split("_")[0] in tickers]
    filings = args.doc or pick_filings(available, args.filings)

    docs = documents(filings, chunks_dir, args.chunks_per_filing)
    print(f"Generating {args.n} questions from {len(docs)} chunks of {len(filings)} filings "
          f"({', '.join(filings)}) with {args.model}")
    rows, tokens = generate(docs, args.n, args.model)
    questions = to_questions(rows, docs)

    run = runs_dir() / datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    info = {"model": args.model, "filings": filings, "chunks": len(docs), "questions": len(questions),
            "with_company_and_year": sum(1 for q in questions if q["ticker"]), "generation_tokens": tokens}
    write(run, questions, info)
    print(f"\n{len(questions)} questions ({info['with_company_and_year']} traced to their filing); tokens: {tokens}")
    for q in questions[:5]:
        print(f"  {q['id']} {q['ticker']} {q['fiscal_year']} {q['category']:<8} {q['question']}")
    print(f"\nWritten: {run}/testset.jsonl and testset.csv (review it before step 1)")
    print(f"Next: docker compose --profile ragas run --rm ragas-answers python -m ragas_eval.answers --testset {run.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
