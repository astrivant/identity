"""
Generate, review, and check private completion manifests or prepare a synchronous Codex adapter.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import TYPE_CHECKING

from jsonschema import ValidationError

from witful.commands.completion import configure
from witful.completion.core import check, plan
from witful.completion.hooks import configuration, handle
from witful.completion.models import Audit
from witful.completion.storage import identity, runtime_directory, snapshots
from witful.files import replace_file
from witful.knowledge.contracts import as_data, schema, structure

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run an explicit local review without changing teaching sources or trusting host hooks.

    Args:
        argv (Sequence[str] | None): Selected arguments or process command line.

    Returns:
        int: Zero for successful coverage or acknowledged handoff, one for gaps, and two for malformed input.
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
    result: object
    try:
        if args.command == "schema":
            result = schema(Audit)
        elif args.command == "hook-config":
            result = configuration(root, args.identity)
        elif args.command == "codex-hook":
            raw = sys.stdin.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("Hook payload exceeds the bounded input limit")
            payload: object = json.loads(raw)
            if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
                raise ValueError("Hook input must be a JSON object")
            result = handle(root, args.identity, payload)
        else:
            current = identity(root)
            workspaces = snapshots((root, *args.workspace))
            if args.command == "plan":
                output: Path = args.output.resolve()
                # Runtime reviews must stay out of source-controlled files and cannot overwrite arbitrary collection inputs.
                directory = runtime_directory(root)
                if not output.is_relative_to(directory) or output.suffix != ".json":
                    raise ValueError("Review plans must be JSON files under the collection's .witful/completion directory")
                before = output.read_bytes() if output.exists() else None
                if before is not None and not args.replace:
                    raise ValueError("A review already exists; use --replace to discard its attestations explicitly")
                audit = plan(current, args.task, workspaces)
                replace_file(output, (json.dumps(as_data(audit), indent=2) + "\n").encode(), expected=before)
                result = {"path": str(output), "concepts": len(audit.entries), "reviewed": False}
            else:
                audit = structure(json.loads(args.input.read_text()), Audit)
                errors = check(audit, current, args.task, workspaces)
                result = {
                    "passed": not errors,
                    "complete": not errors and audit.outcome == "complete",
                    "outcome": audit.outcome,
                    "concepts": len(audit.entries),
                    "errors": list(errors),
                }
                print(json.dumps(result, indent=2))
                return 1 if errors else 0
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, RuntimeError, ValidationError, subprocess.SubprocessError):
        # Native Stop must fail closed without leaking source text, subprocess stderr, prompts, or credential-bearing paths.
        if args.command == "codex-hook":
            print(
                json.dumps(
                    {
                        "decision": "block",
                        "reason": (
                            "Completion audit could not validate local state. "
                            "Check the selected collection, current plan, and supported workspace."
                        ),
                    }
                )
            )
            return 0
        print("Completion operation failed: inspect the selected collection, task, schema, and local workspace.", file=sys.stderr)
        return 2
    return 0
