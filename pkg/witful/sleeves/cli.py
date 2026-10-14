"""
Expose isolated identity sessions with explicit backup and required reconciliation commands.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidTag, UnsupportedAlgorithm
from jsonschema import ValidationError

from witful.commands.sleeves import configure
from witful.exceptions import SleeveError
from witful.knowledge.contracts import as_data, schema
from witful.sleeves import operations, state, supervisor
from witful.sleeves.models import Sleeve

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
