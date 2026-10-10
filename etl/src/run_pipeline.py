"""
Run extraction and chunking for every PDF in data/raw/.

    python -m src.run_pipeline                  # all PDFs, skip what's already up to date
    python -m src.run_pipeline --limit 3        # first 3 PDFs, for development
    python -m src.run_pipeline --scope all      # keep investor material too
    python -m src.run_pipeline --force          # redo everything
    python -m src.run_pipeline --prune          # also delete outputs whose PDF left data/raw

A document counts as up to date only if it was produced by this exact ETL code
and settings (its fingerprint). After pulling a new version of the ETL, or
changing --scope, the affected documents are redone automatically.

Outputs:
    data/clean/<doc_id>.json      contract 1, one per document
    data/chunks/<doc_id>.jsonl    contract 2, one chunk per line
    data/chunks/_stats.csv        one row per document in scope (up to date or redone), for the team
    data/clean/_skipped.csv       documents not processed in the last run, and why

Outputs whose PDF is no longer in data/raw (a company taken out of the
selection) are listed at the end of a full run, because the index loads every
.jsonl in data/chunks. They are deleted only with --prune: they may come from
somewhere else, such as a shared chunks package, and can't be rebuilt without
their PDFs.
"""

import argparse
import csv
import hashlib
import os
import sys
from collections import Counter
from pathlib import Path

from .chunk import chunk_document
from .classify import year_check
from .extract import SkippedDocument, extract_document
from .metadata import load_inventory, metadata_for
from .models import Chunk, Document
from .tokens import TOKENIZER_MODEL

SRC = Path(__file__).resolve().parent


def default_data_dir() -> Path:
    if os.environ.get("DATA_DIR"):
        return Path(os.environ["DATA_DIR"])
    # etl/src/run_pipeline.py -> repository root
    return SRC.parents[1] / "data"


def fingerprint(scope: str) -> str:
    """Hash of the ETL source code and settings. Line endings are normalized so
    Windows and Linux checkouts of the same code give the same fingerprint."""
    h = hashlib.sha256(f"scope={scope};tokenizer={TOKENIZER_MODEL}".encode())
    for path in sorted(SRC.glob("*.py")):
        h.update(path.name.encode())
        h.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


def is_up_to_date(doc_path: Path, chunk_path: Path, current: str) -> bool:
    if not (doc_path.exists() and chunk_path.exists()):
        return False
    try:
        return Document.model_validate_json(doc_path.read_text(encoding="utf-8")).etl_fingerprint == current
    except ValueError:
        return False  # unreadable or old-format file: redo it


def write_atomic(path: Path, text: str) -> None:
    """Write to a temporary file and rename it, so an interrupted run never leaves a half file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def remove_outputs(*paths: Path) -> None:
    for p in paths:
        p.unlink(missing_ok=True)


def orphan_outputs(clean_dir: Path, chunk_dir: Path, doc_ids: set[str]) -> list[Path]:
    """Outputs of documents whose PDF is not in data/raw anymore."""
    found = [*clean_dir.glob("*.json"), *chunk_dir.glob("*.jsonl")]
    return sorted(p for p in found if p.stem not in doc_ids)


def handle_orphans(orphans: list[Path], raw: Path, prune: bool) -> None:
    """List the orphan outputs, or delete them with --prune. A file that can't be
    deleted (open in another program on Windows) is reported and left in place."""
    if not orphans:
        return
    if not prune:
        doc_ids = sorted({p.stem for p in orphans})
        print(f"\n{len(doc_ids)} documents have outputs but no PDF in {raw}, and the index would still load them:")
        print("  " + ", ".join(doc_ids))
        print("Run again with --prune to delete them.")
        return
    for path in orphans:
        try:
            path.unlink()
            print(f"  removed {path.name} (its PDF is no longer in {raw})")
        except OSError as e:
            print(f"  could not remove {path.name}: {e}", file=sys.stderr)


def document_stats(doc: Document, chunks: list[Chunk]) -> dict:
    kinds = Counter(c.content_type for c in chunks)
    sections = Counter(c.section for c in chunks)
    words = [len(c.text.split()) for c in chunks]
    return {
        "doc_id": doc.doc_id,
        "doc_type": doc.doc_type,
        "pages_total": doc.n_pages,
        "pages_kept": len(doc.pages),
        "form_10k_pages": "-".join(map(str, doc.form_10k_pages)) if doc.form_10k_pages else "",
        "fiscal_year": doc.fiscal_year,
        "fiscal_year_end": doc.fiscal_year_end.isoformat() if doc.fiscal_year_end else "",
        "year_check": year_check(doc.fiscal_year, doc.fiscal_year_end),
        "chunks": len(chunks),
        "text_chunks": kinds.get("text", 0),
        "table_chunks": kinds.get("table", 0),
        "avg_words": round(sum(words) / len(words)) if words else 0,
        "max_words": max(words) if words else 0,
        "unknown_section_share": round(sections.get("Unknown", 0) / len(chunks), 2) if chunks else 0,
        "sections": len(sections),
    }


def read_outputs(doc_path: Path, chunk_path: Path) -> tuple[Document, list[Chunk]]:
    doc = Document.model_validate_json(doc_path.read_text(encoding="utf-8"))
    with open(chunk_path, encoding="utf-8") as f:
        chunks = [Chunk.model_validate_json(line) for line in f if line.strip()]
    return doc, chunks


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="FilingLens ETL: PDF -> clean documents -> chunks")
    ap.add_argument("--data-dir", type=Path, default=default_data_dir())
    ap.add_argument("--limit", type=int, default=None, help="process only the first N PDFs")
    ap.add_argument("--scope", choices=["10k", "all"], default="10k")
    ap.add_argument("--force", action="store_true", help="redo documents even if up to date")
    ap.add_argument("--prune", action="store_true", help="delete the outputs of PDFs no longer in data/raw")
    args = ap.parse_args(argv)
    if args.prune and args.limit is not None:
        ap.error("--prune needs a full run: drop --limit")

    raw, clean_dir, chunk_dir = args.data_dir / "raw", args.data_dir / "clean", args.data_dir / "chunks"
    clean_dir.mkdir(parents=True, exist_ok=True)
    chunk_dir.mkdir(parents=True, exist_ok=True)

    inventory = load_inventory(raw / "inventario.csv")
    pdfs = sorted(raw.glob("*.pdf"))[: args.limit]
    if not pdfs:
        print(f"No PDFs found in {raw}", file=sys.stderr)
        return 1

    current = fingerprint(args.scope)
    print(f"ETL fingerprint {current} (scope {args.scope}, tokenizer {TOKENIZER_MODEL})")
    stats, skipped = [], []
    for pdf in pdfs:
        meta = metadata_for(pdf, inventory)
        doc_path = clean_dir / f"{meta['doc_id']}.json"
        chunk_path = chunk_dir / f"{meta['doc_id']}.jsonl"

        # Save what is expensive, but only reuse outputs made by this exact code
        if not args.force and is_up_to_date(doc_path, chunk_path, current):
            doc, chunks = read_outputs(doc_path, chunk_path)
            stats.append(document_stats(doc, chunks))
            print(f"  {pdf.name:<16} up to date")
            continue

        try:
            doc = extract_document(pdf, meta, scope=args.scope, fingerprint=current)
        except SkippedDocument as e:
            skipped.append({"file": pdf.name, "reason": f"{e.reason}: {e}"})
            # Outputs from an earlier run or scope must not reach the index
            remove_outputs(doc_path, chunk_path)
            print(f"  {pdf.name:<16} SKIPPED ({e.reason})")
            continue

        chunks = chunk_document(doc)
        write_atomic(chunk_path, "".join(c.model_dump_json() + "\n" for c in chunks))
        write_atomic(doc_path, doc.model_dump_json(indent=1))  # last: marks the document as done

        s = document_stats(doc, chunks)
        stats.append(s)
        warn = "" if s["year_check"] == "ok" else f"  YEAR {s['year_check'].upper()} ({s['fiscal_year_end']})"
        print(f"  {pdf.name:<16} {s['doc_type']:<13} pages {s['pages_kept']:>3}/{s['pages_total']:<3} "
              f"chunks {s['chunks']:>4} (tables {s['table_chunks']:>3})  "
              f"unknown {s['unknown_section_share']:.0%}  FY end {s['fiscal_year_end']}{warn}")

    if stats:
        write_csv(chunk_dir / "_stats.csv", stats, list(stats[0].keys()))
    write_csv(clean_dir / "_skipped.csv", skipped, ["file", "reason"])
    print(f"\nDone: {len(stats)} documents in scope, {len(skipped)} skipped. Output in {args.data_dir}")

    if args.limit is None:
        doc_ids = {metadata_for(pdf, inventory)["doc_id"] for pdf in pdfs}
        handle_orphans(orphan_outputs(clean_dir, chunk_dir, doc_ids), raw, args.prune)
    return 0


if __name__ == "__main__":
    sys.exit(main())
