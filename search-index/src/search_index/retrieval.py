"""Haystack-syntax filters for the search lane's retrievers."""

from __future__ import annotations

from typing import Any

_FILTER_FIELDS = ("company", "ticker", "fiscal_year", "section")


def _condition(field: str, value: Any) -> dict[str, Any]:
    if isinstance(value, (list, tuple)):
        if not value or any(item == "" for item in value):
            raise ValueError(f"{field}: the list must not be empty or contain empty values")
        return {"field": f"meta.{field}", "operator": "in", "value": list(value)}
    if value == "":
        raise ValueError(f"{field}: the value must not be an empty string")
    return {"field": f"meta.{field}", "operator": "==", "value": value}


def build_filters(
    *,
    company: str | list[str] | None = None,
    ticker: str | list[str] | None = None,
    fiscal_year: int | list[int] | None = None,
    section: str | list[str] | None = None,
) -> dict[str, Any] | None:
    """Filter in Haystack syntax over ``meta.<field>``.

    With no arguments it returns ``None`` (no filter). A single value becomes ``==`` and a list
    becomes ``in``. Several fields are combined with ``AND`` in a fixed order (company, ticker,
    fiscal year, section). An empty string or list raises ``ValueError``: it could never match a
    valid chunk and would return "no results" with no explanation.
    """
    given = {"company": company, "ticker": ticker, "fiscal_year": fiscal_year, "section": section}
    conditions = [_condition(f, given[f]) for f in _FILTER_FIELDS if given[f] is not None]
    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"operator": "AND", "conditions": conditions}

