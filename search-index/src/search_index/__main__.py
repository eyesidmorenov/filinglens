"""Module CLI: ``python -m search_index {health,stats}``.

Prints JSON to stdout and errors to stderr (``error: ...``), and exits non-zero on failure:
1 = the operation failed (or the status is not ``ok``), 2 = bad usage or configuration.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence

from . import admin
from .config import IndexSettings


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m search_index",
        description="Status and counts of the FilingLens Elasticsearch index (read-only).",
    )
    parser.add_argument(
        "--env-prefix",
        default="",
        metavar="PREFIX",
        help="environment variable prefix (e.g. SEARCH_ reads SEARCH_ES_INDEX)",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    commands.add_parser("health", help="cluster and index status (exits non-zero unless ok)")
    commands.add_parser("stats", help="counts by company, year, section and chunk type")
    return parser


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    """Entry point. ``env`` exists so tests can inject it (defaults to ``os.environ``)."""
    args = _build_parser().parse_args(argv)
    try:
        settings = IndexSettings.from_env(env, prefix=args.env_prefix)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        if args.command == "health":
            payload = admin.health(settings)
            code = 0 if payload["status"] == "ok" else 1
        else:
            payload, code = admin.stats(settings), 0
    except Exception as exc:  # noqa: BLE001 - the CLI turns any failure into an exit code
        print(f"error: {type(exc).__name__}: {' '.join(str(exc).split())}", file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return code


if __name__ == "__main__":
    sys.exit(main())
