"""
Plan periodic reviews, accept explicitly reviewed assessments, and render current evidence.
"""

from __future__ import annotations

import argparse
import json
from importlib.resources import files
from typing import TYPE_CHECKING

from jsonschema import ValidationError

from witful.collection.protection import check_collection
from witful.commands.reflection import configure
from witful.files import replace_file
from witful.knowledge.contracts import as_data, schema, structure
from witful.reflection.journal import config, read, record
from witful.reflection.models import Assessment, Config, Review
from witful.reflection.planning import plan
from witful.reflection.plotting import build

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    """
    Expose review boundaries without implicit model calls, publication, or lesson promotion.

    Args:
        argv (Sequence[str] | None): Explicit arguments or process arguments.

    Returns:
        int: Zero on success; parser exit two for invalid or unavailable sources.
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
    try:
        if args.command == "schema":
            print(json.dumps({"settings": schema(Config), "assessment": schema(Assessment), "review": schema(Review)}, indent=2))
            return 0
        output = root / getattr(args, "output", getattr(args, "output_dir", "."))
        if args.command != "example":
            check_collection(root, output)
        if args.command == "example":
            values = json.loads(files("witful.reflection").joinpath("resources/example.json").read_text())
            build(tuple(structure(value, Assessment) for value in values), output, synthetic=True)
        elif args.command == "plan":
            payload = plan(root, args.history_repo or root)
            replace_file(output, (json.dumps(payload, indent=2) + "\n").encode(), expected=output.read_bytes() if output.exists() else None)
            print(json.dumps({"due": payload["due"], "decisions": payload["decision_count"]}))
        elif args.command == "record":
            values = json.loads(args.input.read_text())
            if not isinstance(values, list):
                raise ValueError("Review input must be an array")
            print(record(root, args.history_repo or root, tuple(structure(value, Assessment) for value in values)).id)
        else:
            settings = config(root)
            rounds = read(root)
            if args.command == "check":
                print(f"Validated {len(rounds)} review rounds")
            elif settings.enabled:
                latest = {item.decision_id: item for event in rounds for item in event.assessments}
                build(tuple(latest[key] for key in sorted(latest)), output)
                path = output / "reflections.json"
                replace_file(
                    path,
                    (json.dumps({"reviews": [as_data(event) for event in rounds]}, indent=2) + "\n").encode(),
                    expected=path.read_bytes() if path.exists() else None,
                )
    except (OSError, ValueError, RuntimeError, ValidationError):
        parser.exit(
            2,
            "Reflection failed: check source schemas, complete Git history, evidence, and storage protection locally. "
            "Private diagnostics withheld.\n",
        )
    return 0
