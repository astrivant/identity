"""
Render, inspect, and explicitly push selected awareness figures to a resume repository.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING

from jsonschema import ValidationError

from witful.awareness.github import push
from witful.awareness.models import Bundle, PushConfig
from witful.awareness.rendering import render
from witful.files import replace_file
from witful.knowledge.contracts import schema, structure

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
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path, default=Path("knowledge/awareness.json"))
    parser.add_argument("--output", type=Path, default=Path(".witful/awareness.json"))
    parser.add_argument("command", choices=["build", "push", "schema"])
    args = parser.parse_args(argv)

    try:
        if args.command == "schema":
            print(json.dumps({"config": schema(PushConfig), "bundle": schema(Bundle)}, indent=2))
            return 0

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
