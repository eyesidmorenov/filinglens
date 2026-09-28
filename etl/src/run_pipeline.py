"""
Run extraction and chunking for every PDF in data/raw/.

    python -m src.run_pipeline                  # all PDFs, skip what's already done
    python -m src.run_pipeline --limit 3        # first 3 PDFs, for development
    python -m src.run_pipeline --scope all      # keep investor material too
    python -m src.run_pipeline --force          # redo everything

Outputs:
    data/clean/<doc_id>.json      contract 1, one per document
    data/chunks/<doc_id>.jsonl    contract 2, one chunk per line
    data/chunks/_stats.csv        one row per document, for the team
    data/clean/_skipped.csv       documents that could not be processed, and why
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

from .chunk import chunk_document
from .extract import ScannedDocumentError, extract_document
from .metadata import load_inventory, metadata_for
from .models import Document


def default_data_dir() -> Path:
    if os.environ.get("DATA_DIR"):
        return Path(os.environ["DATA_DIR"])
    # etl/src/run_pipeline.py -> repository root
    return Path(__file__).resolve().parents[2] / "data"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="FilingLens ETL: PDF -> clean documents -> chunks")
    ap.add_argument("--data-dir", type=Path, default=default_data_dir())
    ap.add_argument("--limit", type=int, default=None, help="process only the first N PDFs")
    ap.add_argument("--scope", choices=["10k", "all"], default="10k")
    ap.add_argument("--force", action="store_true", help="redo documents already on disk")
    args = ap.parse_args(argv)

    raw, clean_dir, chunk_dir = args.data_dir / "raw", args.data_dir / "clean", args.data_dir / "chunks"
    clean_dir.mkdir(parents=True, exist_ok=True)
    chunk_dir.mkdir(parents=True, exist_ok=True)

    inventory = load_inventory(raw / "inventario.csv")
    pdfs = sorted(raw.glob("*.pdf"))[: args.limit]
    if not pdfs:
        print(f"No PDFs found in {raw}", file=sys.stderr)
        return 1

    stats, skipped = [], []
    for pdf in pdfs:
        meta = metadata_for(pdf, inventory)
        doc_path = clean_dir / f"{meta['doc_id']}.json"
        chunk_path = chunk_dir / f"{meta['doc_id']}.jsonl"

        # Save what is expensive: reuse extraction and chunks already on disk
        if doc_path.exists() and chunk_path.exists() and not args.force:
            print(f"  {pdf.name:<16} already done")
            continue

        try:
            doc = extract_document(pdf, meta, scope=args.scope)
        except ScannedDocumentError as e:
            skipped.append({"file": pdf.name, "reason": f"scanned: {e}"})
            print(f"  {pdf.name:<16} SKIPPED (scanned)")
            continue

        doc_path.write_text(doc.model_dump_json(indent=1), encoding="utf-8")
        chunks = chunk_document(doc)
        with open(chunk_path, "w", encoding="utf-8") as f:
            for c in chunks:
                f.write(c.model_dump_json() + "\n")

        kinds = Counter(c.content_type for c in chunks)
        sections = Counter(c.section for c in chunks)
        words = [len(c.text.split()) for c in chunks]
        stats.append({
            "doc_id": doc.doc_id,
            "doc_type": doc.doc_type,
            "pages_total": doc.n_pages,
            "pages_kept": len(doc.pages),
            "form_10k_pages": "-".join(map(str, doc.form_10k_pages)) if doc.form_10k_pages else "",
            "chunks": len(chunks),
            "text_chunks": kinds.get("text", 0),
            "table_chunks": kinds.get("table", 0),
            "avg_words": round(sum(words) / len(words)) if words else 0,
            "max_words": max(words) if words else 0,
            "unknown_section_share": round(sections.get("Unknown", 0) / len(chunks), 2) if chunks else 0,
            "sections": len(sections),
        })
        s = stats[-1]
        print(f"  {pdf.name:<16} {s['doc_type']:<13} pages {s['pages_kept']:>3}/{s['pages_total']:<3} "
              f"chunks {s['chunks']:>4} (tables {s['table_chunks']:>3})  unknown {s['unknown_section_share']:.0%}")

    if stats:
        with open(chunk_dir / "_stats.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(stats[0].keys()))
            w.writeheader()
            w.writerows(stats)
    if skipped:
        with open(clean_dir / "_skipped.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["file", "reason"])
            w.writeheader()
            w.writerows(skipped)
    print(f"\nDone: {len(stats)} processed, {len(skipped)} skipped. Output in {args.data_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
