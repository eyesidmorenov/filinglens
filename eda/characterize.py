"""
Characterizes the downloaded filings. Step 3 of the EDA.

It does not clean or transform anything. It only measures and reports,
so whoever builds the extraction knows exactly what they are working with.

What it answers:
  1. How many pages a real 10-K has
  2. Whether the text extracts readable or there are scanned documents
  3. Whether they have numbered Item sections, and in which format
  4. How many characters come out, to estimate the chunks
  5. Whether the file name matches what the document says inside
  6. Whether there are duplicates
  7. Which language they are in
  8. How many tables each one has

Output files and their columns/keys are a data contract read by the notebook
(eda_filinglens.ipynb), so they keep their original names:
    data/eda/caracterizacion.csv, data/eda/caracterizacion.json

Usage:
    python characterize.py
    python characterize.py --sample AAPL_2019    # just one, in detail
"""

import argparse
import contextlib
import csv
import io
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

try:
    import pymupdf as fitz
except ImportError:          # older versions of the library
    import fitz

ROOT = Path(__file__).parent.parent
INPUT = ROOT / "data" / "raw"
OUTPUT = ROOT / "data" / "eda"

# Threshold: fewer characters per page than this suggests a scan or no text
MIN_CHARS_PER_PAGE = 200

# The 10-K sections we care about
KEY_ITEMS = ["1", "1A", "3", "5", "7", "7A", "8"]

# Common English words, for a simple language check
ENGLISH_MARKERS = {"the", "and", "of", "to", "in", "for", "that", "with", "our", "we"}


def item_pattern(num):
    """
    Builds the pattern to find 'Item 1A' in its different forms.

    10-Ks write the same section in different ways:
        Item 1A.  |  ITEM 1A  |  Item 1A —  |  Item 1A:
    That is why the pattern is flexible about the separator after the number.
    """
    return re.compile(rf"\bitem\s+{num}\b[\.\:\s\-—]", re.IGNORECASE)


def find_items(text):
    """Returns which items appear and how many times each one."""
    found = {}
    for num in KEY_ITEMS:
        matches = item_pattern(num).findall(text)
        if matches:
            found[f"Item {num}"] = len(matches)
    return found


def item_formats(text):
    """
    How the items are written. Tells us whether the chunking pattern
    has to be flexible or can be strict.

    The labels (MAYUSCULAS, Capitalizado, minusculas) are kept as they are
    because the notebook reads them from caracterizacion.json.
    """
    raw = re.findall(r"\b(item\s+\d+[A-Z]?)\s*([\.\:\-—])", text, re.IGNORECASE)
    forms = Counter()
    for heading, sep in raw[:200]:
        if heading.isupper():
            case = "MAYUSCULAS"      # uppercase
        elif heading.istitle() or heading[0].isupper():
            case = "Capitalizado"    # capitalized
        else:
            case = "minusculas"      # lowercase
        forms[f"{case} + '{sep}'"] += 1
    return dict(forms.most_common(5))


def english_score(text):
    """Simple check: how many English markers appear."""
    words = set(re.findall(r"[a-z]+", text[:50000].lower()))
    return len(ENGLISH_MARKERS & words)


def check_consistency(text, ticker, year):
    """
    Does the content match the file name?
    A mislabeled document would make the bot cite the wrong company.
    """
    head = text[:20000]
    return {
        "ticker_en_texto": bool(re.search(rf"\b{re.escape(ticker)}\b", head, re.IGNORECASE)),
        "anio_en_texto": bool(re.search(rf"\b{year}\b", head)),
        "dice_10k": bool(re.search(r"\b(form\s+10-?k|annual\s+report)\b", head, re.IGNORECASE)),
    }


def analyze(pdf_path):
    """Opens a PDF and returns all its metrics."""
    name = pdf_path.stem            # AAPL_2019
    ticker, year = name.split("_")

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        return {"archivo": name, "error": f"{type(e).__name__}: {e}"}

    pages = doc.page_count
    texts = []
    empty_pages = 0
    tables = 0

    for i, page in enumerate(doc):
        t = page.get_text()
        texts.append(t)
        if len(t.strip()) < MIN_CHARS_PER_PAGE:
            empty_pages += 1
        # the table detector is slow, so we run it on a sample of pages
        if i < 40:
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    tables += len(page.find_tables().tables)
            except Exception:
                pass

    full = "\n".join(texts)
    doc.close()

    n_chars = len(full)
    n_words = len(full.split())
    items = find_items(full)

    # Keys are a data contract with the notebook: keep them as they are
    return {
        "archivo": name,
        "ticker": ticker,
        "anio": int(year),
        "peso_mb": round(pdf_path.stat().st_size / 1024**2, 2),
        "paginas": pages,
        "caracteres": n_chars,
        "palabras": n_words,
        "chars_por_pagina": round(n_chars / pages) if pages else 0,
        "paginas_sin_texto": empty_pages,
        "pct_sin_texto": round(100 * empty_pages / pages, 1) if pages else 0,
        "tablas_en_40p": tables,
        "items_encontrados": len(items),
        "items": items,
        "formatos_item": item_formats(full),
        "marcadores_ingles": english_score(full),
        "coherencia": check_consistency(full, ticker, year),
        "hash": hashlib.md5(full.encode("utf-8", "replace")).hexdigest()[:12],
        "fragmentos_est": round(n_chars / 1000),   # at 1,000 chars per chunk
    }


def print_detail(r):
    print(f"\n{'=' * 70}\n{r['archivo']}\n{'=' * 70}")
    if "error" in r:
        print(f"  ERROR: {r['error']}")
        return
    print(f"  Pages:              {r['paginas']}")
    print(f"  Size:               {r['peso_mb']} MB")
    print(f"  Characters:         {r['caracteres']:,}")
    print(f"  Words:              {r['palabras']:,}")
    print(f"  Chars per page:     {r['chars_por_pagina']:,}")
    print(f"  Pages without text: {r['paginas_sin_texto']} ({r['pct_sin_texto']}%)")
    print(f"  Tables (40 pages):  {r['tablas_en_40p']}")
    print(f"  Estimated chunks:   ~{r['fragmentos_est']}")
    print(f"  English markers:    {r['marcadores_ingles']}/10")
    print(f"\n  Items found ({r['items_encontrados']}/{len(KEY_ITEMS)}):")
    for k, v in r["items"].items():
        print(f"     {k:<10} appears {v} times")
    missing = [f"Item {n}" for n in KEY_ITEMS if f"Item {n}" not in r["items"]]
    if missing:
        print(f"     missing: {', '.join(missing)}")
    print("\n  Item formats:")
    for k, v in r["formatos_item"].items():
        print(f"     {k:<26} {v} times")
    c = r["coherencia"]
    print("\n  File name vs content:")
    print(f"     ticker in the text:  {'yes' if c['ticker_en_texto'] else 'NO'}")
    print(f"     year in the text:    {'yes' if c['anio_en_texto'] else 'NO'}")
    print(f"     says 10-K:           {'yes' if c['dice_10k'] else 'NO'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", help="analyze a single document in detail")
    args = ap.parse_args()

    pdfs = sorted(INPUT.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs in {INPUT}. Run download_sample.py first")
        sys.exit(1)

    if args.sample:
        target = INPUT / f"{args.sample}.pdf"
        if not target.exists():
            print(f"{target} does not exist")
            sys.exit(1)
        print_detail(analyze(target))
        return

    print(f"Analyzing {len(pdfs)} documents...\n")
    results = []
    for p in pdfs:
        print(f"  {p.stem}...", end=" ", flush=True)
        r = analyze(p)
        results.append(r)
        print("error" if "error" in r else f"{r['paginas']} pages, {r['caracteres']:,} chars")

    ok = [r for r in results if "error" not in r]
    if not ok:
        print("\nNo document could be opened.")
        sys.exit(1)

    # ---------- Summary ----------
    print(f"\n{'=' * 70}\nSUMMARY\n{'=' * 70}")

    pages = [r["paginas"] for r in ok]
    chars = [r["caracteres"] for r in ok]
    print(f"Documents analyzed: {len(ok)}")
    print(f"\nPages:       min {min(pages)}   max {max(pages)}   average {sum(pages)//len(pages)}")
    print(f"Characters:  min {min(chars):,}   max {max(chars):,}   average {sum(chars)//len(chars):,}")
    print(f"Total estimated chunks: ~{sum(r['fragmentos_est'] for r in ok):,}")

    # ---------- Scans ----------
    print(f"\n{'-' * 70}\nEXTRACTABLE TEXT")
    suspicious = [r for r in ok if r["pct_sin_texto"] > 20]
    if suspicious:
        print("  Documents with more than 20% of pages without text:")
        for r in suspicious:
            print(f"     {r['archivo']:<14} {r['pct_sin_texto']}% without text")
        print("  Check whether they are scans. A scan is useless without OCR.")
    else:
        print("  Every document has extractable text. No scans.")

    # ---------- Items ----------
    print(f"\n{'-' * 70}\nITEM SECTIONS")
    complete = [r for r in ok if r["items_encontrados"] == len(KEY_ITEMS)]
    print(f"  With all {len(KEY_ITEMS)} key items: {len(complete)}/{len(ok)}")
    for r in ok:
        missing = [n for n in KEY_ITEMS if f"Item {n}" not in r["items"]]
        status = "complete" if not missing else f"missing {missing}"
        print(f"     {r['archivo']:<14} {r['items_encontrados']}/{len(KEY_ITEMS)}  {status}")

    formats = Counter()
    for r in ok:
        formats.update(r["formatos_item"])
    print("\n  Writing formats found across the corpus:")
    for k, v in formats.most_common(8):
        print(f"     {k:<26} {v}")
    if len(formats) > 1:
        print("  There is more than one format. The chunking pattern must be flexible.")

    # ---------- Consistency ----------
    print(f"\n{'-' * 70}\nFILE NAME VS CONTENT")
    problems = [r for r in ok if not all(r["coherencia"].values())]
    if problems:
        for r in problems:
            c = r["coherencia"]
            failed = [k for k, v in c.items() if not v]
            print(f"     {r['archivo']:<14} not confirmed: {', '.join(failed)}")
        print("  Check by hand. A mislabeled document cites the wrong company.")
    else:
        print("  All match: ticker, year and document type confirmed in the text.")

    # ---------- Language ----------
    print(f"\n{'-' * 70}\nLANGUAGE")
    not_english = [r for r in ok if r["marcadores_ingles"] < 8]
    if not_english:
        for r in not_english:
            print(f"     {r['archivo']:<14} only {r['marcadores_ingles']}/10 English markers")
    else:
        print("  All in English.")

    # ---------- Duplicates ----------
    print(f"\n{'-' * 70}\nDUPLICATES")
    hashes = Counter(r["hash"] for r in ok)
    repeated = {h: c for h, c in hashes.items() if c > 1}
    if repeated:
        for h in repeated:
            same = [r["archivo"] for r in ok if r["hash"] == h]
            print(f"     identical content: {', '.join(same)}")
    else:
        print(f"  No duplicates. The {len(ok)} documents are all different.")

    # ---------- Tables ----------
    print(f"\n{'-' * 70}\nTABLES")
    total_t = sum(r["tablas_en_40p"] for r in ok)
    print(f"  Detected in the first 40 pages of each document: {total_t}")
    print(f"  Average per document: {total_t // len(ok)}")
    print("  Financial statements come in tables. See the deliverable 2 spike.")

    # ---------- Save ----------
    OUTPUT.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT / "caracterizacion.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    columns = ["archivo", "ticker", "anio", "peso_mb", "paginas", "caracteres",
               "palabras", "chars_por_pagina", "paginas_sin_texto", "pct_sin_texto",
               "tablas_en_40p", "items_encontrados", "fragmentos_est", "hash"]
    with open(OUTPUT / "caracterizacion.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(ok)

    print(f"\n{'=' * 70}")
    print(f"Saved to {OUTPUT}")
    print("  caracterizacion.csv    table to review and plot")
    print("  caracterizacion.json   full detail, including the items")


if __name__ == "__main__":
    main()
