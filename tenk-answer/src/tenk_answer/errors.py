"""Exceptions raised by tenk_answer."""


class TenkAnswerError(Exception):
    """Base class for all tenk_answer errors."""


class InvalidDocumentError(TenkAnswerError, ValueError):
    """An input document does not satisfy Contract 3 (missing or invalid fields)."""


class MalformedResponseError(TenkAnswerError):
    """The model did not return a valid `submit_answer` tool call."""


class GenerationError(TenkAnswerError):
    """The Anthropic API call failed (API error, connection error or timeout)."""
