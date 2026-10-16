"""Pulls the `answer` text out of the model's JSON reply while it is still streaming."""

from __future__ import annotations

import json

ANSWER_FIELD = "answer"

_HIGH_SURROGATES = range(0xD800, 0xDC00)


class AnswerTextExtractor:
    """Feed raw JSON pieces in order; each call returns the newly decoded characters of the top-level `answer`.

    The reply is `{"status": ..., "answer": "...", "sources": [...]}`. Pieces can split anywhere, including inside
    an escape such as `\\"` or `\\u00e9`. Only the top-level `answer` value is emitted: an `"answer"` key nested in
    `sources`, or the word inside another string, is ignored. Everything after the closing quote is ignored.

    The emitted text is a preview. The parser may still renumber its [n] markers or replace it entirely
    (no-source-no-answer), so the final `Answer` is the one to show once the reply is complete.
    """

    def __init__(self) -> None:
        self.text = ""  # everything emitted so far
        self.done = False  # the answer string has closed
        self._depth = 0
        self._in_string = False
        self._escaped = False  # previous char was a backslash, outside the answer
        self._expect_key = False  # the next string at depth 1 is a key
        self._is_key = False
        self._buffer = ""  # the key being read, outside the answer
        self._last_key: str | None = None
        self._in_answer = False
        self._escape = ""  # pending escape sequence inside the answer, e.g. "\\u00"
        self._high_surrogate = ""  # a "\\uD83D" waiting for its low half

    def feed(self, piece: str) -> str:
        out: list[str] = []
        for char in piece:
            if self.done:
                break
            if self._in_answer:
                self._answer_char(char, out)
            elif self._in_string:
                self._string_char(char)
            else:
                self._structure_char(char)
        emitted = "".join(out)
        self.text += emitted
        return emitted

    def _structure_char(self, char: str) -> None:
        if char in "{[":
            self._depth += 1
            self._expect_key = char == "{" and self._depth == 1
        elif char in "}]":
            self._depth -= 1
        elif self._depth == 1 and char == ",":
            self._expect_key = True
        elif self._depth == 1 and char == ":":
            self._expect_key = False
        elif char == '"':
            if self._depth == 1 and not self._expect_key and self._last_key == ANSWER_FIELD:
                self._in_answer = True
                return
            self._in_string = True
            self._is_key = self._depth == 1 and self._expect_key
            self._buffer = ""

    def _string_char(self, char: str) -> None:
        if self._escaped:
            self._escaped = False
        elif char == "\\":
            self._escaped = True
        elif char == '"':
            self._in_string = False
            if self._is_key:
                self._last_key = self._buffer
            return
        if self._is_key:
            self._buffer += char

    def _answer_char(self, char: str, out: list[str]) -> None:
        if self._escape:
            self._escape += char
            if self._escape.startswith("\\u") and len(self._escape) < 6:
                return
            self._decode_escape(out)
        elif char == "\\":
            self._escape = char
        elif char == '"':
            self._flush_surrogate(out)
            self._in_answer = False
            self.done = True
        else:
            self._flush_surrogate(out)
            out.append(char)

    def _decode_escape(self, out: list[str]) -> None:
        sequence, self._escape = self._escape, ""
        if self._high_surrogate and sequence.startswith("\\u"):
            pair, self._high_surrogate = self._high_surrogate + sequence, ""
            out.append(_loads(pair))
            return
        self._flush_surrogate(out)
        if sequence.startswith("\\u") and int(sequence[2:], 16) in _HIGH_SURROGATES:
            self._high_surrogate = sequence
            return
        out.append(_loads(sequence))

    def _flush_surrogate(self, out: list[str]) -> None:
        if self._high_surrogate:
            # a high surrogate with no low half can't be encoded; show a replacement char instead
            self._high_surrogate = ""
            out.append("�")


def _loads(sequence: str) -> str:
    try:
        decoded: str = json.loads(f'"{sequence}"')
    except json.JSONDecodeError:
        return "�"
    # an unpaired low surrogate decodes but can't be encoded later
    return decoded.encode("utf-8", "replace").decode("utf-8")
