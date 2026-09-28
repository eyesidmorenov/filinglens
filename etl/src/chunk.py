"""
Document -> chunks (contract 2).

Text is cut by section first and by size second: each section is split into
chunks of about CHUNK_WORDS words with OVERLAP_WORDS of overlap, never cutting
a sentence in half. BGE embeddings read at most 512 tokens; 300 words stays
well below that.

Financial tables become their own chunks, rendered as Markdown so each number
keeps its column header. A long table is split by rows, repeating its header.
"""

import re

from .layout import is_table_row, is_year_header, rows_to_markdown
from .models import Chunk, Document
from .sections import label_lines

CHUNK_WORDS = 300
OVERLAP_WORDS = 45
TABLE_MAX_ROWS = 40
# Short rows just above a table are its title and column headers ("2019 | 2018")
HEADER_LOOKBACK = 6
# Rows inside a table without numbers ("Operating expenses:") are short labels
SHORT_ROW_WORDS = 12
MAX_LABEL_ROWS_INSIDE = 4

ENDS_SENTENCE = re.compile(r"[.!?][\"”)]?$")
STARTS_SENTENCE = re.compile(r"^[A-Z(\"“•]")


def split_sentences(words: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """
    Join (page, word) pairs into sentences. Each sentence keeps the page of its
    first word, so a chunk can cite the page where it starts.
    """
    sentences, current, page = [], [], None
    for i, (p, w) in enumerate(words):
        if not current:
            page = p
        current.append(w)
        nxt = words[i + 1][1] if i + 1 < len(words) else ""
        if ENDS_SENTENCE.search(w) and (not nxt or STARTS_SENTENCE.match(nxt)):
            sentences.append((page, " ".join(current)))
            current = []
    if current:
        sentences.append((page, " ".join(current)))
    return sentences


def split_long_sentence(page: int, sentence: str) -> list[tuple[int, str]]:
    """A 'sentence' longer than a chunk (lists, run-on legal text) is cut by words."""
    words = sentence.split()
    if len(words) <= CHUNK_WORDS:
        return [(page, sentence)]
    step = CHUNK_WORDS - OVERLAP_WORDS
    return [(page, " ".join(words[i:i + CHUNK_WORDS])) for i in range(0, len(words), step)]


def window_sentences(sentences: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Group sentences into chunks of ~CHUNK_WORDS words, overlapping by ~OVERLAP_WORDS."""
    chunks, current, count = [], [], 0
    for page, s in sentences:
        n = len(s.split())
        if current and count + n > CHUNK_WORDS:
            chunks.append((current[0][0], " ".join(t for _, t in current)))
            # Carry the last sentences of the previous chunk as overlap
            tail, tail_count = [], 0
            for prev in reversed(current):
                tail_count += len(prev[1].split())
                if tail_count > OVERLAP_WORDS:
                    break
                tail.insert(0, prev)
            current, count = tail, sum(len(t.split()) for _, t in tail)
        current.append((page, s))
        count += n
    if current:
        chunks.append((current[0][0], " ".join(t for _, t in current)))
    return chunks


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.split(" | ")]


def is_short(line: str) -> bool:
    return len(line.replace(" | ", " ").split()) <= SHORT_ROW_WORDS


def merge_table_gaps(segs: list[dict]) -> list[dict]:
    """
    Join table / short labels / table on the same page into one table, so an
    income statement is not cut at 'Operating expenses:'.
    """
    out: list[dict] = []
    for seg in segs:
        if (
            seg["kind"] == "table"
            and len(out) >= 2
            and out[-1]["kind"] == "text"
            and out[-2]["kind"] == "table"
            and out[-1]["section"] == out[-2]["section"] == seg["section"]
            and len(out[-1]["items"]) <= MAX_LABEL_ROWS_INSIDE
            and all(is_short(l) for _, l in out[-1]["items"])
            and out[-2]["items"][-1][0] == seg["items"][0][0]
        ):
            gap = out.pop()
            out[-1]["items"].extend(gap["items"] + seg["items"])
            continue
        if seg["kind"] == "table" and out and out[-1]["kind"] == "table" and out[-1]["section"] == seg["section"]:
            out[-1]["items"].extend(seg["items"])
            continue
        out.append(seg)
    return out


def segments(doc: Document) -> list[dict]:
    """
    Walk the document and emit segments that share section and kind:
    {'kind': 'text'|'table', 'section': str, 'items': [(page, line), ...]}
    """
    pages = [p.text.split("\n") for p in doc.pages]
    labels = label_lines(pages)
    out: list[dict] = []
    for page, lines, page_labels in zip(doc.pages, pages, labels):
        for i, (line, section) in enumerate(zip(lines, page_labels)):
            kind = "table" if is_table_row(cells(line)) else "text"
            last = out[-1] if out else None
            if last and last["kind"] == kind and last["section"] == section:
                last["items"].append((page.page, line))
                continue
            if kind == "table" and last and last["kind"] == "text" and last["section"] == section:
                # Pull the column header rows that sit right above the first number row
                header = []
                while last["items"] and len(header) < HEADER_LOOKBACK:
                    p, prev = last["items"][-1]
                    if p == page.page and is_short(prev):
                        header.insert(0, last["items"].pop())
                    else:
                        break
                if not last["items"]:
                    out.pop()
                out.append({"kind": kind, "section": section, "items": header + [(page.page, line)]})
                continue
            out.append({"kind": kind, "section": section, "items": [(page.page, line)]})
    return merge_table_gaps(out)


def text_chunks(items: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """(page, text) pairs for a prose segment; page is where each chunk starts."""
    words = [(page, w) for page, line in items for w in line.replace(" | ", " ").split()]
    sentences = [
        piece for page, s in split_sentences(words) for piece in split_long_sentence(page, s)
    ]
    return window_sentences(sentences)


def table_chunks(items: list[tuple[int, str]], section: str) -> list[tuple[int, str]]:
    """(page, markdown) pairs; long tables split by rows, repeating the header."""
    rows = [cells(line) for _, line in items]
    pages = [p for p, _ in items]
    first_row = 0
    while first_row < len(rows) and (not is_table_row(rows[first_row]) or is_year_header(rows[first_row])):
        first_row += 1
    lead, body = rows[:first_row], rows[first_row:]
    # One-cell lead rows are titles ("CONSOLIDATED STATEMENTS OF OPERATIONS");
    # multi-cell lead rows are column headers ("2019 | 2018 | 2017")
    caption = " ".join(r[0] for r in lead if len(r) == 1)
    columns = [r for r in lead if len(r) > 1]
    if not columns:
        width = max(len(r) for r in body)
        columns = [[""] * width]
    title = f"Table ({section})" + (f": {caption}" if caption else "")

    out = []
    for i in range(0, len(body), TABLE_MAX_ROWS):
        block = columns + body[i:i + TABLE_MAX_ROWS]
        page = pages[0] if i == 0 else pages[first_row + i]
        out.append((page, title + "\n" + rows_to_markdown(block, header_rows=len(columns))))
    return out


def chunk_document(doc: Document) -> list[Chunk]:
    chunks: list[Chunk] = []
    per_page_counter: dict[int, int] = {}
    for seg in segments(doc):
        if seg["kind"] == "table" and sum(is_table_row(cells(l)) for _, l in seg["items"]) >= 2:
            pieces, content_type = table_chunks(seg["items"], seg["section"]), "table"
        else:
            pieces, content_type = text_chunks(seg["items"]), "text"
        for page, text in pieces:
            if len(text.split()) < 5:
                continue
            per_page_counter[page] = per_page_counter.get(page, 0) + 1
            chunks.append(Chunk(
                chunk_id=f"{doc.doc_id}_p{page}_c{per_page_counter[page]}",
                doc_id=doc.doc_id,
                text=text,
                section=seg["section"],
                page=page,
                company=doc.company,
                ticker=doc.ticker,
                fiscal_year=doc.fiscal_year,
                content_type=content_type,
                doc_type=doc.doc_type,
            ))
    return chunks
