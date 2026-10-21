"""Suggested questions shown under an answer (option A, agreed with Elkin on 2026-10-21).

Built from templates, without Claude: instant, free, and only for companies and years we have.
Contract 4 is not touched: the chat asks for them at GET /suggestions after the answer.

Rules (Elkin):
  - Never suggest what Claude declines: no comparisons between companies, no calculations or
    growth rates, no investment advice. Every template asks about one company and one year.
  - 2 or 3 suggestions, all about the same company:
      1. another topic, same year
      2. the same topic, the year before
      3. a Yahoo Finance year, when the question was about a 10-K year and the company has one
"""

from __future__ import annotations

from dataclasses import dataclass

from . import pipeline, yahoo

MAX_SUGGESTIONS = 3


@dataclass(frozen=True)
class Topic:
    name: str
    keywords: tuple[str, ...]  # words in the question that mean this topic (lower case)
    template: str  # {name} = official company name, {year} = fiscal year
    yahoo_figure: str | None  # the snapshot figure that answers it in the years after the 10-Ks


# In order of preference: the first one that is not the current topic is suggested
TOPICS = (
    Topic("revenue", ("revenue", "net sales", "sales"),
          "What was the total revenue of {name} in fiscal {year}?", "Total Revenue"),
    Topic("risks", ("risk",),
          "What were the main risk factors for {name} in fiscal {year}?", None),
    Topic("net income", ("net income", "profit", "earnings"),
          "What was the net income of {name} in fiscal {year}?", "Net Income"),
    Topic("business", ("business", "segment", "overview", "products"),
          "How did {name} describe its business in fiscal {year}?", None),
    Topic("cash flow", ("cash flow",),
          "What was the operating cash flow of {name} in fiscal {year}?", "Operating Cash Flow"),
)


def current_topic(question: str) -> Topic | None:
    text = question.lower()
    return next((t for t in TOPICS if any(word in text for word in t.keywords)), None)


def _in_index(ticker: str, year: int) -> bool:
    return (ticker, year) in pipeline.company_names()


def _answerable(topic: Topic, ticker: str, year: int) -> bool:
    """The 10-Ks answer every topic; a Yahoo year only the figures its snapshot has for that year."""
    if _in_index(ticker, year):
        return True
    if not topic.yahoo_figure:
        return False
    snapshot = yahoo.load_snapshot(ticker)
    return bool(snapshot) and topic.yahoo_figure in yahoo.figures(snapshot, year)


def suggest(question: str) -> list[str]:
    """Up to 3 questions about the same company, or [] when the question had no company and year."""
    ticker, year, message = pipeline.resolve_company_year(question)
    if message:
        return []

    name = pipeline.company_name(ticker)
    topic = current_topic(question)
    picks: list[tuple[Topic, int]] = []

    # 1. Another topic, same year
    other = next((t for t in TOPICS if t != topic and _answerable(t, ticker, year)), None)
    if other:
        picks.append((other, year))

    # 2. The same topic, the year before
    if topic and _answerable(topic, ticker, year - 1):
        picks.append((topic, year - 1))

    # 3. The latest Yahoo year, when the question was about a 10-K year
    later = [y for y in yahoo.years(ticker) if not _in_index(ticker, y)]
    if _in_index(ticker, year) and later:
        figure = topic if topic and _answerable(topic, ticker, later[-1]) else TOPICS[0]
        if _answerable(figure, ticker, later[-1]):
            picks.append((figure, later[-1]))

    suggestions = []
    for t, y in picks:
        text = t.template.format(name=name, year=y)
        # Safety net: every suggestion must be a question the API can answer
        if text not in suggestions and not pipeline.resolve_company_year(text)[2]:
            suggestions.append(text)
    return suggestions[:MAX_SUGGESTIONS]
