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

from witful.collection.protection import check_collection
from witful.commands.storage import configure
from witful.lessons import append_lesson, new_lesson, read_journal, rebuild_database
from witful.storage import open_store

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
    configure(parser)
    return execute(parser.parse_args(argv), parser)


def execute(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """
    Execute an already parsed domain command.

    Args:
        args (argparse.Namespace): Validated arguments from the shared hierarchy or standalone parser.
        parser (argparse.ArgumentParser): Owning parser for consistent error reporting.

    Returns:
        int: Selected operation status.
    """
    repo = Path(args.repo).resolve()
    home = Path(args.home).expanduser().resolve()
    journal = repo / "lessons.jsonl"
    database = home / "lessons.sqlite3"
    endpoint = os.environ.get("WITFUL_DATABASE_URL")

    try:
        check_collection(repo, home, remote=endpoint is not None and args.command != "check")

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
