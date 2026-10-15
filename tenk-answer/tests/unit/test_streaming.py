from __future__ import annotations

import json

import pytest

from tenk_answer.streaming import AnswerTextExtractor


def feed_all(pieces: list[str]) -> tuple[str, list[str]]:
    extractor = AnswerTextExtractor()
    emitted = [extractor.feed(piece) for piece in pieces]
    assert extractor.text == "".join(emitted)
    return extractor.text, emitted


def char_by_char(text: str) -> list[str]:
    return list(text)


def payload(answer: str, **extra: object) -> str:
    return json.dumps({"status": "answered", "answer": answer, "sources": [], **extra})


@pytest.mark.parametrize(
    "answer",
    [
        "NVIDIA relies on TSMC [1].",
        'He said "quoted" text [1][2].',
        "Line one\nLine two\ttabbed \\ backslash / slash",
        "Accents: café, señor, 日本",
        "Emoji: 😀 done",
        "",
    ],
)
def test_matches_json_decoding_for_any_split(answer: str) -> None:
    raw = payload(answer)
    # every character on its own is the worst case: escapes and \uXXXX split across pieces
    assert feed_all(char_by_char(raw))[0] == answer
    assert feed_all([raw])[0] == answer
    for cut in range(len(raw)):
        assert feed_all([raw[:cut], raw[cut:]])[0] == answer


def test_ascii_escaped_unicode_and_surrogate_pairs() -> None:
    raw = json.dumps({"status": "answered", "answer": "café 😀"}, ensure_ascii=True)
    assert "\\u00e9" in raw and "\\ud83d\\ude00" in raw
    assert feed_all(char_by_char(raw))[0] == "café 😀"


def test_lone_high_surrogate_becomes_replacement_char() -> None:
    raw = '{"answer": "a\\ud83d b"}'
    assert feed_all(char_by_char(raw))[0] == "a\ufffd b"


def test_emits_text_as_it_arrives() -> None:
    _, emitted = feed_all(['{"status": "answered", "answer": "Sup', "ply ", 'risks."', ', "sources": []}'])
    assert emitted == ["Sup", "ply ", "risks.", ""]


def test_ignores_everything_after_the_answer() -> None:
    raw = '{"status": "answered", "answer": "Done.", "sources": [{"doc_id": "D1", "excerpt": "more text"}]}'
    extractor = AnswerTextExtractor()
    assert extractor.feed(raw) == "Done."
    assert extractor.done
    assert extractor.feed("trailing junk") == ""


def test_answer_key_order_does_not_matter() -> None:
    raw = '{"sources": [{"doc_id": "D1", "excerpt": "x"}], "answer": "Last.", "status": "answered"}'
    assert feed_all([raw])[0] == "Last."


@pytest.mark.parametrize(
    "raw",
    [
        # "answer" as a key nested inside sources
        '{"status": "answered", "sources": [{"answer": "nested"}], "answer": "top"}',
        # "answer" as a value, not a key
        '{"status": "answer", "answer": "top"}',
        # an escaped "answer" key inside another string
        '{"status": "x \\"answer\\": \\"fake\\"", "answer": "top"}',
        # whitespace and newlines around the colon
        '{\n  "status" : "answered",\n  "answer"\n  :\n  "top"\n}',
    ],
)
def test_only_the_top_level_answer_is_emitted(raw: str) -> None:
    assert feed_all(char_by_char(raw))[0] == "top"


def test_no_answer_field_emits_nothing() -> None:
    extractor = AnswerTextExtractor()
    assert extractor.feed('{"status": "answered", "sources": []}') == ""
    assert not extractor.done


def test_non_json_text_emits_nothing() -> None:
    assert feed_all(["I can't answer that in JSON."])[0] == ""
