"""
Record, inspect, replay, and seed the versioned decision audit through Witful Life.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from jsonschema import ValidationError

from witful.collection.protection import check_collection
from witful.files import replace_file
from witful.knowledge.contracts import as_data, schema, structure
from witful.life.contracts import current_decisions
from witful.life.journal import read_archive, record_decision
from witful.life.models import Decision, Event, Snapshot
from witful.life.replay import prefix, render

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["main"]


def _schemas(root: Path, *, check: bool) -> None:
    """
    Derive closed audit schemas from the same attrs models used at every ingestion boundary.

    Args:
        root (Path): Source checkout containing generated schema files.
        check (bool): Validate committed output without changing it.

    Returns:
        None: Schemas match the current source models.

    Raises:
        ValueError: Check mode finds missing or stale schemas.
    """
    for name, model in (("decision", Decision), ("event", Event), ("snapshot", Snapshot)):
        path = root / "knowledge/schemas" / f"life-{name}.schema.json"
        generated = schema(model)

        if check:
            if not path.exists() or json.loads(path.read_text()) != generated:
                raise ValueError("Life schemas are stale; run witful life schemas")
        else:
            content = (json.dumps(generated, indent=2, sort_keys=True) + "\n").encode()
            replace_file(path, content, expected=path.read_bytes() if path.exists() else None)


def main(argv: Sequence[str] | None = None) -> int:
    """
    Execute one explicit audit operation without implicitly publishing records to a remote service.

    Args:
        argv (Sequence[str] | None): Explicit argument sequence or process arguments.

    Returns:
        int: Zero on success, or parser exit two for invalid input or unavailable storage.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--namespace", default=os.environ.get("WITFUL_DATABASE_NAMESPACE", "default"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("schemas", help="Generate schemas from the audit models")
    commands.add_parser("check", help="Validate the complete audit, snapshots, and committed schemas")
    record = commands.add_parser("record", help="Append a reviewed decision JSON document, or its explicit revision")
    record.add_argument("--input", type=Path, required=True)
    record.add_argument("--source-revision", help="Import knowledge inputs from an existing Git revision")
    show = commands.add_parser("show", help="Inspect current choices or their retained history")
    show.add_argument("--key")
    show.add_argument("--history", action="store_true")
    build = commands.add_parser("build", help="Render today's view of the decision history without rewriting source records")
    build.add_argument("--output-dir", type=Path, default=Path("docs/assets"))
    replay = commands.add_parser("replay", help="Reconstruct a journal prefix and its saved knowledge plots")
    replay.add_argument("--through", help="Inclusive last event ID; omitted means the complete journal")
    replay.add_argument("--output-dir", type=Path, default=Path(".cache/life-replay"))
    replay.add_argument("--allow-renderer-drift", action="store_true")
    replay.add_argument("--from-database", action="store_true", help="Use the PostgreSQL archive without reading current source journals")
    commands.add_parser("seed", help="Seed WITFUL_DATABASE_URL with the validated local audit and replay snapshots")
    args = parser.parse_args(argv)
    root = args.repo.resolve()

    try:
        check_collection(
            root,
            root / args.output_dir if args.command in {"build", "replay"} else root,
            remote=args.command == "seed" or (args.command == "replay" and args.from_database),
        )
        if args.command == "schemas":
            _schemas(root, check=False)
            return 0
        if args.command == "record":
            draft = structure(json.loads(args.input.read_text()), Decision)
            print(record_decision(root, draft, source_revision=args.source_revision).id)
            return 0

        # The optional driver is loaded only for an explicitly requested database operation.
        remote = args.command == "seed" or (args.command == "replay" and args.from_database)

        if remote:
            endpoint = os.environ.get("WITFUL_DATABASE_URL")

            if endpoint is None:
                raise ValueError("Set WITFUL_DATABASE_URL for this operation")

            try:
                from witful.life.postgres import PostgreSQLLifeStore
            except ImportError:
                raise ValueError("PostgreSQL requires poetry install --extras postgres") from None

            store = PostgreSQLLifeStore(endpoint, args.namespace)

            if args.command == "seed":
                print(json.dumps({"added_events": store.seed(read_archive(root))}))
                return 0

            archive = store.load()
        else:
            archive = read_archive(root)

        if args.command == "check":
            _schemas(root, check=True)
            print(f"Validated {len(archive.events)} decisions and {len(archive.snapshots)} replay snapshots")
            return 0
        if args.command == "show":
            events = archive.events if args.history else current_decisions(archive)
            selected = [as_data(event) for event in events if args.key is None or event.decision.key == args.key]
            print(json.dumps(selected, indent=2, ensure_ascii=False))
            return 0

        historical = args.command == "replay"
        archive = prefix(archive, args.through if historical else None)
        output = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir

        for path in render(archive, root, output, historical=historical, allow_drift=historical and args.allow_renderer_drift):
            print(path)

    except ValidationError as error:
        parser.exit(2, f"witful life: invalid source field {list(error.absolute_path)} ({error.validator})\n")
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"witful life: {error}\n")

    return 0
