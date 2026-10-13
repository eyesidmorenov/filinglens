"""Read-only companion for the FilingLens index (see README.md).

Provides what ``index/`` and ``search/`` do not: ``admin.health()`` and ``admin.stats()`` for the
API, and ``build_filters`` to filter by company, fiscal year and section.
"""

from . import admin
from .config import IndexSettings
from .errors import IndexCompatibilityError
from .retrieval import build_filters
from .store import assert_index_compatible

__all__ = [
    "IndexCompatibilityError",
    "IndexSettings",
    "admin",
    "assert_index_compatible",
    "build_filters",
]
