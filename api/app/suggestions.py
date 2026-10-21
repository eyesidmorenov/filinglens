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


def _key(question: str) -> tuple[str, int, str] | None:
    """What a question asks about: (ticker, fiscal year, topic), or None when we can't tell."""
    ticker, year, message = pipeline.resolve_company_year(question)
    topic = current_topic(question)
    if message or topic is None:
        return None
    return ticker, year, topic.name


def suggest(question: str, asked: list[str] | tuple[str, ...] = ()) -> list[str]:
    """Up to 3 questions about the same company, or [] when the question had no company and year.

    `asked` = the questions already asked in this conversation: nothing about the same
    company, year and topic is suggested again, even if it was written differently.
    """
    ticker, year, message = pipeline.resolve_company_year(question)
    if message:
        return []

    name = pipeline.company_name(ticker)
    topic = current_topic(question)
    done = {key for q in (question, *asked) if (key := _key(q))}

    # 1. Another topic, same year (all of them: the first ones may have been asked already)
    other_topics = [(t, year) for t in TOPICS if t != topic]
    # 2. The same topic, the year before
    year_before = [(topic, year - 1)] if topic else []
    # 3. The latest Yahoo year, when the question was about a 10-K year
    later = [y for y in yahoo.years(ticker) if not _in_index(ticker, y)]
    yahoo_year = []
    if _in_index(ticker, year) and later:
        figure = topic if topic and _answerable(topic, ticker, later[-1]) else TOPICS[0]
        yahoo_year = [(figure, later[-1])]

    def usable(t: Topic, y: int) -> bool:
        return (ticker, y, t.name) not in done and _answerable(t, ticker, y)

    # One of each kind first (the first usable one), then more topics of the same year to fill up to 3
    picks = []
    for group in (other_topics, year_before, yahoo_year):
        pick = next(((t, y) for t, y in group if usable(t, y)), None)
        if pick:
            picks.append(pick)
    picks += [(t, y) for t, y in other_topics if (t, y) not in picks and usable(t, y)]

    suggestions = []
    for t, y in picks:
        text = t.template.format(name=name, year=y)
        # Safety net: every suggestion must be a question the API can answer
        if text not in suggestions and not pipeline.resolve_company_year(text)[2]:
            suggestions.append(text)
        if len(suggestions) == MAX_SUGGESTIONS:
            break
    return suggestions
