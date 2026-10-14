"""
Validate, inspect, record, and render the knowledge hierarchy through one package command.
"""

from __future__ import annotations

import argparse
import fcntl
import json
from datetime import UTC, datetime
from pathlib import Path

from attrs import evolve
from jsonschema import ValidationError

from witful.collection.protection import check_collection
from witful.files import replace_file
from witful.knowledge.applications import append_application, application_id, effective_applications, read_applications
from witful.knowledge.compiler import compile_identity, index
from witful.knowledge.contracts import as_data, schema, structure
from witful.knowledge.metrics import usage
from witful.knowledge.models import Application, Catalog
from witful.knowledge.plotting import write_plots
from witful.knowledge.rendering import graph_data
from witful.lessons import read_journal

__all__ = ["main"]


def _write_json(path: Path, value: object) -> None:
    """
    Replace a generated JSON artifact only when its deterministic bytes change.

    Args:
        path (Path): Generated file destination.
        value (object): JSON-compatible data.

    Returns:
        None: The file is current and unchanged outputs retain their modification times.
    """
    content = (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
    replace_file(path, content, expected=path.read_bytes() if path.exists() else None)


def main() -> int:
    """
    Run explicit, bounded knowledge operations without contacting an external service.

    Returns:
        int: Zero for a successful operation, two for invalid sources or filesystem errors.
    """
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Additional commands: init, lessons, life, repertoire, checkpoints, reflection, awareness, collection, "
            "privacy scan, registry; each accepts --help."
        ),
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Existing knowledge checkout; defaults to the current directory")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="Validate journal, source schemas, hierarchy, and every application")
    build = commands.add_parser("build", help="Regenerate schemas, graph export, and README plots")
    build.add_argument("--output-dir", type=Path, default=Path("docs/assets"))
    show = commands.add_parser("show", help="List concept IDs or inspect one concept and its recorded usage")
    show.add_argument("identifier", nargs="?")
    record = commands.add_parser("record", help="Append a sourced application or a complete revised observation")
    record.add_argument("--task", required=True)
    record.add_argument("--discipline", required=True)
    record.add_argument("--concept", action="append", required=True)
    record.add_argument("--outcome", choices=["unassessed", "verified", "unsuccessful"], default="unassessed")
    record.add_argument("--evidence", required=True)
    args = parser.parse_args()
    root = args.repo.resolve()

    try:
        check_collection(root, root / args.output_dir if args.command == "build" else root)
        catalog = structure(json.loads((root / "knowledge/catalog.json").read_text()), Catalog)
        identity = compile_identity(read_journal(root / "lessons.jsonl"), catalog)
        nodes, _ = index(identity)

        # Serialize usage writers independently of journal writers. Neither operation edits the other source.
        with (root / ".applications.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            journal = root / "knowledge/applications.jsonl"
            applications = read_applications(journal)
            counts = usage(identity, applications)

            if args.command == "record":
                identifiers: set[str] = set()

                for requested in args.concept:
                    matches = [key for key in nodes if key == requested or key.startswith(requested)]

                    if len(matches) != 1:
                        raise ValueError(f"Concept prefix must resolve uniquely: {requested}")

                    identifiers.add(matches[0])

                event = Application(
                    "", args.task, args.discipline, tuple(sorted(identifiers)), args.outcome, args.evidence, datetime.now(UTC).isoformat()
                )
                event = evolve(event, id=application_id(event))
                print(append_application(journal, event, identity))
                return 0

            if args.command == "show":
                if args.identifier:
                    if args.identifier not in nodes:
                        raise ValueError("Unknown concept ID; run show without an ID to list available concepts")

                    print(json.dumps({"concept": as_data(nodes[args.identifier]), "usage": as_data(counts[args.identifier])}, indent=2))
                else:
                    print(
                        json.dumps(
                            [{"id": key, "kind": type(node).__name__, "name": node.name} for key, node in sorted(nodes.items())], indent=2
                        )
                    )
                return 0

            schemas = {"catalog": schema(Catalog), "application": schema(Application)}

            if args.command == "check":
                for name, generated in schemas.items():
                    if json.loads((root / f"knowledge/schemas/{name}.schema.json").read_text()) != generated:
                        raise ValueError("Generated schemas are stale; run witful build and review the diff")

                print(f"Validated {len(nodes)} concepts and {len(effective_applications(applications))} task/context applications")
                return 0

            # All sources validate before any derived artifact changes. Inputs, not old images or database contents, own the result.
            output = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
            graph = graph_data(identity, applications)

            for name, generated in schemas.items():
                _write_json(root / f"knowledge/schemas/{name}.schema.json", generated)

            _write_json(output / "knowledge-graph.json", graph)

            for path in write_plots(identity, applications, output):
                print(path)

    except ValidationError as error:
        parser.exit(2, f"identity knowledge: invalid source field {list(error.absolute_path)} ({error.validator})\n")
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"identity knowledge: {error}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
