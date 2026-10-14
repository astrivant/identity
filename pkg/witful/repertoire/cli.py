"""
Maintain explicit tool and problem observations beside the lesson hierarchy.
"""

from __future__ import annotations

import argparse
import fcntl
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from attrs import evolve
from jsonschema import ValidationError

from witful.collection.protection import check_collection
from witful.files import replace_file
from witful.knowledge.compiler import compile_identity, index
from witful.knowledge.contracts import as_data, schema, structure
from witful.knowledge.models import Catalog
from witful.lessons import read_journal
from witful.repertoire.journal import counts, use_id, validate
from witful.repertoire.models import Inventory, Use
from witful.repertoire.plotting import write_plots

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """
    Validate definitions, record actual use, or render current frequency and taxonomy.

    Args:
        argv (Sequence[str] | None): Explicit arguments or process arguments.

    Returns:
        int: Zero on success; parser exit two for invalid sources.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    commands.add_parser("build")
    record = commands.add_parser("record")
    record.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.repo.resolve()

    try:
        check_collection(root, root / "docs/assets")
        inventory_path = root / "knowledge/repertoire.json"
        inventory = structure(json.loads(inventory_path.read_text()), Inventory) if inventory_path.exists() else Inventory()
        catalog = structure(json.loads((root / "knowledge/catalog.json").read_text()), Catalog)
        nodes, _ = index(compile_identity(read_journal(root / "lessons.jsonl"), catalog))

        # Serialize observed-use updates separately; a task revision never erases its earlier evidence.
        with (root / ".tool-use.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = root / "knowledge/tool-uses.jsonl"
            old = path.read_bytes() if path.exists() else None
            events = [structure(json.loads(line), Use) for line in (old or b"").decode().splitlines() if line.strip()]
            validate(inventory, events, set(nodes))

            if args.command == "record":
                draft = structure(json.loads(args.input.read_text()), Use)
                event = evolve(draft, observed_at=datetime.now(UTC).isoformat(), id=use_id(draft))

                if any(previous.id == event.id for previous in events):
                    print(event.id)
                    return 0

                validate(inventory, [*events, event], set(nodes))
                prefix = (old or b"").rstrip(b"\n")
                content = prefix + (b"\n" if prefix else b"") + (json.dumps(as_data(event), sort_keys=True) + "\n").encode()
                replace_file(path, content, expected=old)
                print(event.id)
                return 0

            if args.command == "check":
                print(f"Validated {len(inventory.tools)} tools, {len(inventory.problems)} problem types, and {len(events)} observations")
                return 0

            for name, model in (("repertoire", Inventory), ("tool-use", Use)):
                path = root / f"knowledge/schemas/{name}.schema.json"
                content = (json.dumps(schema(model), sort_keys=True, indent=2) + "\n").encode()
                replace_file(path, content, expected=path.read_bytes() if path.exists() else None)

            destination = root / "docs/assets"

            # The exported input set lets readers reproduce these views without inferring uses from the inventory.
            path = destination / "repertoire.json"
            payload = {"inventory": as_data(inventory), "events": [as_data(event) for event in events], "counts": counts(inventory, events)}
            content = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()
            replace_file(path, content, expected=path.read_bytes() if path.exists() else None)

            for path in write_plots(inventory, events, destination):
                print(path)

    except (OSError, ValueError, RuntimeError, ValidationError):
        parser.exit(2, "Invalid repertoire source, reference, or filesystem state; check the schemas and source permissions.\n")

    return 0
