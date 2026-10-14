"""
Record, compare, mirror, and render explicit project checkpoints.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from typing import TYPE_CHECKING

from jsonschema import ValidationError

from witful.checkpoints.diff import compare
from witful.checkpoints.journal import read, record
from witful.checkpoints.models import Checkpoint
from witful.checkpoints.plotting import build
from witful.checkpoints.storage import SQLiteCheckpointStore, open_store
from witful.collection.protection import check_collection
from witful.commands.checkpoints import configure
from witful.files import replace_file
from witful.knowledge.contracts import as_data, schema

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    """
    Execute one bounded operation, keeping remote writes explicit and plots out of recording.

    Args:
        argv (Sequence[str] | None): Explicit arguments or process command line.

    Returns:
        int: Zero on success; parser exit two for invalid data, references, or unavailable storage.
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
    root = args.repo.resolve()
    database = args.database or root / ".witful/checkpoints.sqlite3"

    try:
        check_collection(
            root,
            database,
            root / args.output_dir if args.command == "build" else root,
            remote=os.environ.get("WITFUL_DATABASE_URL") is not None and (args.command == "sync" or getattr(args, "from_database", False)),
        )
        if args.command == "schemas":
            path = root / "knowledge/schemas/checkpoint.schema.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            content = (json.dumps(schema(Checkpoint), indent=2, sort_keys=True) + "\n").encode()
            replace_file(path, content, expected=path.read_bytes() if path.exists() else None)
            return 0

        if args.command == "record":
            event = record(root, args.project, args.project_id)

            # Journal persistence precedes the disposable local mirror; an interrupted sync is safe to retry.
            SQLiteCheckpointStore(database, args.namespace).seed(read(root / "knowledge/checkpoints.jsonl"))
            print(event.id)
            return 0

        stored = args.command in {"build", "diff"} and args.from_database
        events = (
            open_store(database, os.environ.get("WITFUL_DATABASE_URL"), args.namespace).load()
            if stored
            else read(root / "knowledge/checkpoints.jsonl")
        )

        if args.command == "check":
            print(f"Validated {len(events)} project checkpoints")
        elif args.command == "sync":
            print(
                json.dumps({"added_checkpoints": open_store(database, os.environ.get("WITFUL_DATABASE_URL"), args.namespace).seed(events)})
            )
        elif args.command == "diff":
            if len(events) < 2 and (not args.before or not args.after):
                raise ValueError("Record two checkpoints or supply two existing checkpoint IDs")

            indexed = {event.id: event for event in events}
            before = indexed.get(args.before) if args.before else events[-2]
            after = indexed.get(args.after) if args.after else events[-1]

            if before is None or after is None:
                raise ValueError("Unknown checkpoint ID")

            print(json.dumps([as_data(item) for item in compare(before, after)], indent=2))
        else:
            output = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir

            for path in build(events, output, args.limit):
                print(path)
    except (OSError, ValueError, RuntimeError, ValidationError, subprocess.TimeoutExpired):
        parser.exit(
            2,
            "Checkpoint operation failed; validate source records, project HEAD, requested IDs, and storage access. "
            "No source text or credentials were logged.\n",
        )

    return 0
