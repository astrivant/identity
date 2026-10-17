"""
Render, inspect, and explicitly push selected professional representation figures to a resume repository.
"""

from __future__ import annotations

import argparse
import json
from typing import TYPE_CHECKING

from jsonschema import ValidationError

from witful.collection.protection import check_collection
from witful.commands.representation import configure
from witful.files import replace_file
from witful.knowledge.contracts import schema, structure
from witful.representation.github import push
from witful.representation.models import Bundle, PushConfig
from witful.representation.rendering import render

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """
    Build from current evidence; remote publication occurs only for an explicit push.

    Args:
        argv (Sequence[str] | None): Explicit CLI arguments, or process arguments.

    Returns:
        int: Zero after local build or accepted dispatch; parser exit two on failure.
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

    try:
        if args.command == "schema":
            print(json.dumps({"config": schema(PushConfig), "bundle": schema(Bundle)}, indent=2))
            return 0

        check_collection(args.repo.resolve(), args.repo / args.output)
        config = structure(json.loads((args.repo / args.config).read_text()), PushConfig)
        content = render(args.repo.resolve(), config.figures)
        output = args.repo / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        replace_file(output, content, expected=output.read_bytes() if output.exists() else None)

        if args.command == "push":
            commit = push(config.repository, content)
            print(f"Dispatch accepted for {config.repository} at {commit}; follow https://github.com/{config.repository}/actions")
        else:
            print(output)

    except ValidationError as error:
        parser.exit(2, f"awareness: invalid source field {list(error.absolute_path)} ({error.validator})\n")
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"awareness: {error}\n")

    return 0
