"""
Document -> chunks (contract 2).

Text is cut by section first and by size second. Size is measured in tokens of
the embedding model (see tokens.py): a chunk closes when the next sentence
would pass CHUNK_TARGET_TOKENS, carries about OVERLAP_TOKENS of the previous
chunk, never cuts a sentence in half, and never exceeds CHUNK_MAX_TOKENS.

Financial tables become their own chunks, rendered as Markdown so each number
keeps its column header. A long table is split by rows, repeating its header.

Every function that measures size takes a `count` function, so tests can use a
simple word counter and the pipeline uses the real tokenizer.
"""

from collections.abc import Callable

from .layout import is_table_row, is_year_header, rows_to_markdown
from .models import Chunk, Document
from .sections import label_lines
from .tokens import CHUNK_MAX_TOKENS, CHUNK_TARGET_TOKENS, OVERLAP_TOKENS, count_tokens

Counter = Callable[[str], int]

# Short rows just above a table are its title and column headers ("2019 | 2018")
HEADER_LOOKBACK = 6
# Rows inside a table without numbers ("Operating expenses:") are short labels
SHORT_ROW_WORDS = 12
MAX_LABEL_ROWS_INSIDE = 4

SENTENCE_END_CHARS = (".", "!", "?", '."', ".”", ".)")
SENTENCE_START = ('"', "“", "(", "•")


def ends_sentence(word: str) -> bool:
    return word.endswith(SENTENCE_END_CHARS)


def starts_sentence(word: str) -> bool:
    return bool(word) and (word[0].isupper() or word.startswith(SENTENCE_START))


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
        if ends_sentence(w) and (not nxt or starts_sentence(nxt)):
            sentences.append((page, " ".join(current)))
            current = []
    if current:
        sentences.append((page, " ".join(current)))
    return sentences


def split_long_sentence(page: int, sentence: str, count: Counter) -> list[tuple[int, str]]:
    """
    A 'sentence' longer than a chunk (lists, run-on legal text) is cut into
    pieces of at most CHUNK_TARGET_TOKENS, each repeating the last ~OVERLAP_TOKENS
    of the previous piece.
    """
    if count(sentence) <= CHUNK_TARGET_TOKENS:
        return [(page, sentence)]
    words = sentence.split()
    sizes = [count(w) for w in words]
    pieces, start = [], 0
    while start < len(words):
        end, total = start, 0
        while end < len(words) and (total + sizes[end] <= CHUNK_TARGET_TOKENS or end == start):
            total += sizes[end]
            end += 1
        pieces.append((page, " ".join(words[start:end])))
        if end >= len(words):
            break
        # Step back over the last OVERLAP_TOKENS of this piece, but always move forward
        back, overlap = end, 0
        while back - 1 > start and overlap + sizes[back - 1] <= OVERLAP_TOKENS:
            back -= 1
            overlap += sizes[back]
        start = back
    return pieces


def window_sentences(sentences: list[tuple[int, str]], count: Counter) -> list[tuple[int, str]]:
    """
    Group sentences into chunks of about CHUNK_TARGET_TOKENS, overlapping by
    about OVERLAP_TOKENS. The overlap is dropped when it would push a chunk past
    CHUNK_MAX_TOKENS, so the cap always holds.
    """
    sized = [(page, s, count(s)) for page, s in sentences]
    chunks, current, total = [], [], 0
    for page, s, n in sized:
        if current and total + n > CHUNK_TARGET_TOKENS:
            chunks.append((current[0][0], " ".join(t for _, t, _ in current)))
            tail, tail_total = [], 0
            for prev in reversed(current):
                if tail_total + prev[2] > OVERLAP_TOKENS:
                    break
                tail.insert(0, prev)
                tail_total += prev[2]
            if tail_total + n > CHUNK_MAX_TOKENS:
                tail, tail_total = [], 0
            current, total = tail, tail_total
        current.append((page, s, n))
        total += n
    if current:
        chunks.append((current[0][0], " ".join(t for _, t, _ in current)))
    return chunks


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.split(" | ")]


def is_short(line: str) -> bool:
    return len(line.replace(" | ", " ").split()) <= SHORT_ROW_WORDS


def looks_like_table_header(line: str) -> bool:
    """
    Can this line sit above a table as its title or column header?
    Yes: "CONSOLIDATED STATEMENTS OF OPERATIONS", "Years ended", "Net sales:",
    "(In millions)", "2019 | 2018 | 2017". No: the end of a prose sentence
    ("as a percentage of revenue."), which must stay with its paragraph.
    """
    c = cells(line)
    if len(c) >= 2:
        return True
    text = c[0]
    if not text or not is_short(text) or text.endswith((".", ";", ",")):
        return False
    return text[0].isupper() or text[0] == "("


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
        for line, section in zip(lines, page_labels):
            kind = "table" if is_table_row(cells(line)) else "text"
            last = out[-1] if out else None
            if last and last["kind"] == kind and last["section"] == section:
                last["items"].append((page.page, line))
                continue
            if kind == "table" and last and last["kind"] == "text" and last["section"] == section:
                # Pull the title and column header rows that sit right above the first number row
                header = []
                while last["items"] and len(header) < HEADER_LOOKBACK:
                    p, prev = last["items"][-1]
                    if p == page.page and looks_like_table_header(prev):
                        header.insert(0, last["items"].pop())
                    else:
                        break
                if not last["items"]:
                    out.pop()
                out.append({"kind": kind, "section": section, "items": header + [(page.page, line)]})
                continue
            out.append({"kind": kind, "section": section, "items": [(page.page, line)]})
    return merge_table_gaps(out)


def text_chunks(items: list[tuple[int, str]], count: Counter) -> list[tuple[int, str]]:
    """(page, text) pairs for a prose segment; page is where each chunk starts."""
    words = [(page, w) for page, line in items for w in line.replace(" | ", " ").split()]
    sentences = [
        piece for page, s in split_sentences(words) for piece in split_long_sentence(page, s, count)
    ]
    return window_sentences(sentences, count)


def table_chunks(items: list[tuple[int, str]], section: str, count: Counter) -> list[tuple[int, str]] | None:
    """
    (page, markdown) pairs; long tables split by rows, repeating title and header.
    None when the rows are only headers (e.g. year rows), so the caller keeps them as text.
    """
    rows = [cells(line) for _, line in items]
    pages = [p for p, _ in items]
    first_row = 0
    while first_row < len(rows) and (not is_table_row(rows[first_row]) or is_year_header(rows[first_row])):
        first_row += 1
    lead, body = rows[:first_row], rows[first_row:]
    if not body:
        return None
    # One-cell lead rows are titles ("CONSOLIDATED STATEMENTS OF OPERATIONS");
    # multi-cell lead rows are column headers ("2019 | 2018 | 2017")
    caption = " ".join(r[0] for r in lead if len(r) == 1)
    columns = [r for r in lead if len(r) > 1] or [[""] * max(len(r) for r in body)]
    title = f"Table ({section})" + (f": {caption}" if caption else "")

    def render(block: list[list[str]]) -> str:
        return title + "\n" + rows_to_markdown(columns + block, header_rows=len(columns))

    out, block, block_start = [], [], 0
    for i, row in enumerate(body):
        if block and count(render(block + [row])) > CHUNK_MAX_TOKENS:
            out.append((pages[first_row + block_start], render(block)))
            block, block_start = [], i
        block.append(row)
    if block:
        out.append((pages[first_row + block_start] if out else pages[0], render(block)))
    return out


def chunk_document(doc: Document, count: Counter = count_tokens) -> list[Chunk]:
    chunks: list[Chunk] = []
    per_page_counter: dict[int, int] = {}
    for seg in segments(doc):
        pieces, content_type = None, "table"
        if seg["kind"] == "table" and sum(is_table_row(cells(l)) for _, l in seg["items"]) >= 2:
            pieces = table_chunks(seg["items"], seg["section"], count)
        if pieces is None:
            pieces, content_type = text_chunks(seg["items"], count), "text"
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
