"""
Search or extend the versioned lesson archive.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sqlite3
import tempfile
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sapience.lessons import append_lesson, new_lesson, read_journal, rebuild_database
from sapience.storage import open_store

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run one bounded archive operation while serializing local writers.

    Args:
        argv (Sequence[str] | None): Explicit arguments, or process arguments when None.

    Returns:
        int: Zero on success, two for actionable input or filesystem failures.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("SAPIENCE_HOME", Path.cwd() / ".sapience")))
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--namespace", default=os.environ.get("SAPIENCE_DATABASE_NAMESPACE", "default"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sync", help="Synchronize the selected lesson index from the versioned export")
    commands.add_parser("status", help="Show locations, provenance count, and retained history size")
    commands.add_parser("check", help="Validate JSONL and SQL in a temporary database without updating runtime state")
    lookup = commands.add_parser("search", help="Find relevant lessons; terms are literal words")
    lookup.add_argument("terms")
    lookup.add_argument("--history", action="store_true")
    lookup.add_argument("--limit", type=int, default=10)
    add = commands.add_parser("add", help="Append sourced guidance or a correction; Git publication is separate")
    add.add_argument("--topic", required=True)
    add.add_argument("--lesson", required=True)
    add.add_argument("--source", required=True)
    add.add_argument("--supersedes")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    home = Path(args.home).expanduser().resolve()
    journal = repo / "lessons.jsonl"
    database = home / "lessons.sqlite3"
    endpoint = os.environ.get("SAPIENCE_DATABASE_URL")

    try:
        # Preserve local writer serialization; remote readers can consume read-only mounted journals.
        needs_lock = args.command == "add" or (endpoint is None and args.command != "check")
        context = (repo / ".lessons.lock").open("a") if needs_lock else nullcontext(None)
        with context as lock:
            if lock is not None:
                fcntl.flock(lock, fcntl.LOCK_EX)

            if args.command == "add":
                record = new_lesson(args.topic, args.lesson, args.source, datetime.now(UTC).isoformat(), args.supersedes)
                print(append_lesson(journal, record).id)

            records = read_journal(journal)

            if args.command == "check":
                with tempfile.TemporaryDirectory(prefix="identity-check-") as directory:
                    rebuild_database(Path(directory) / "lessons.sqlite3", records)

                print(f"Validated {len(records)} lessons and SQLite resources")
                return 0

            store = open_store(database, database_url=endpoint, namespace=args.namespace)
            store.sync(records)

            if args.command == "search":
                print(json.dumps(store.search(args.terms, history=args.history, limit=args.limit), indent=2, ensure_ascii=False))
            elif args.command in {"status", "sync"}:
                superseded = {record.supersedes for record in records if record.supersedes}
                print(
                    json.dumps(
                        {
                            "repository": str(repo),
                            "backend": "postgresql" if endpoint is not None else "sqlite",
                            "database": "remote (endpoint redacted)" if endpoint is not None else str(database),
                            "namespace": args.namespace,
                            "counts_scope": "source",
                            "total": len(records),
                            "current": len(records) - len(superseded),
                        },
                        indent=2,
                    )
                )

    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        parser.exit(2, f"identity: {error}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
