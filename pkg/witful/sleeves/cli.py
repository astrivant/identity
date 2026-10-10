"""
Expose isolated identity sessions with explicit backup and required reconciliation commands.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidTag, UnsupportedAlgorithm
from jsonschema import ValidationError

from witful.knowledge.contracts import as_data, schema
from witful.sleeves import operations, state, supervisor
from witful.sleeves.models import Sleeve, SleeveError

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run one multisleeving operation and keep private subprocess/source errors out of terminal output.

    Args:
        argv (Sequence[str] | None): Explicit arguments or process arguments.

    Returns:
        int: Zero for success; nonzero for incomplete reconciliation or invalid input.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    starting = commands.add_parser("start", help="Create and back up a private isolated session from current remote main")
    starting.add_argument("--repo", type=Path, required=True)
    starting.add_argument("--directory", type=Path, required=True)
    starting.add_argument("--name", required=True)
    starting.add_argument("--base", default="main")
    starting.add_argument("--remote", default="origin")
    starting.add_argument("--key-dir", type=Path)
    checkpoint = commands.add_parser("checkpoint", help="Validate, sign, and push named changes to this sleeve")
    checkpoint.add_argument("--repo", type=Path, default=Path.cwd())
    checkpoint.add_argument("--paths", nargs="*", default=[])
    checkpoint.add_argument("--message", default="Checkpoint identity sleeve")
    finishing = commands.add_parser("finish", help="Reconcile and close only after remote integration is verified")
    finishing.add_argument("--repo", type=Path, default=Path.cwd())
    finishing.add_argument("--pull-request", action="store_true", help="Propose review instead of directly pushing the integration branch")
    supervised = commands.add_parser("run", help="Supervise a workload and checkpoint/reconcile on exit or termination")
    supervised.add_argument("--repo", type=Path, default=Path.cwd())
    supervised.add_argument("--paths", nargs="*", default=[])
    supervised.add_argument("--shutdown-seconds", type=float, default=90)
    supervised.add_argument("--stop-seconds", type=float, default=10)
    supervised.add_argument("--pull-request", action="store_true")
    supervised.add_argument("workload", nargs=argparse.REMAINDER)
    for name in ("status", "guard", "backup"):
        descriptions = {
            "status": "List local sleeves",
            "guard": "Fail normal session shutdown until closed",
            "backup": "Push existing sleeve commits without staging incomplete source edits",
        }
        command = commands.add_parser(name, help=descriptions[name])
        command.add_argument("--repo", type=Path, default=Path.cwd())
    commands.add_parser("schema", help="Print the closed local receipt schema")
    args = parser.parse_args(argv)
    os.umask(0o077)

    try:
        if args.command == "schema":
            output: object = schema(Sleeve)
        elif args.command == "start":
            output = as_data(
                operations.start(args.repo, args.directory, name=args.name, base=args.base, remote=args.remote, keys=args.key_dir)
            )
        elif args.command == "checkpoint":
            output = as_data(operations.checkpoint(args.repo, tuple(args.paths), args.message))
        elif args.command == "finish":
            output = as_data(operations.finish(args.repo, pull_request=args.pull_request))
        elif args.command == "run":
            workload = args.workload[1:] if args.workload[:1] == ["--"] else args.workload
            return supervisor.run(
                args.repo,
                tuple(workload),
                paths=tuple(args.paths),
                shutdown_seconds=args.shutdown_seconds,
                stop_seconds=args.stop_seconds,
                pull_request=args.pull_request,
            )
        elif args.command == "backup":
            output = as_data(operations.backup(args.repo))
        elif args.command == "guard":
            operations.guard(args.repo)
            output = {"closed": True}
        else:
            output = [as_data(item) for item in state.sessions(args.repo)]
    except SleeveError as error:
        parser.exit(2, f"{error}\n")
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, InvalidTag, UnsupportedAlgorithm, ValidationError):
        parser.exit(2, "Sleeve validation failed. Inspect sources, keys, and configuration locally; private details withheld.\n")

    print(json.dumps(output, indent=2))
    return 0
