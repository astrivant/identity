"""
Expose bounded PR and recovery helpers without treating chat command mentions as execution.
"""

from __future__ import annotations

import argparse
import json
from typing import TYPE_CHECKING

from witful.commands.delivery import configure

from . import prs, recovery
from .common import arrays, exclusive, read

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run the selected explicit delivery operation using existing Git and provider authentication.

    Args:
        argv (Sequence[str] | None): Argument vector; None reads the process arguments.

    Returns:
        int: Zero after the requested stage succeeds; parser errors exit with status two.
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
    if args.remote and args.operation in ("publish", "apply"):
        parser.error("Publication uses the receipt destination; do not supply --remote")
    remotes = tuple(args.remote or ["origin"])
    if len(remotes) != 1 and args.operation != "show":
        parser.error("Mutation selects exactly one remote; receipts bind publication to it")
    try:
        if args.group in ("pr", "mr") and args.operation == "show":
            rows = prs.inventory(args.repo, read(args.dependencies) if args.dependencies else {}, remotes)
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                for index, row in enumerate(rows, 1):
                    size = "unknown" if row["additions"] is None else str(prs.number(row["additions"]) + prs.number(row["deletions"]))
                    title = str(row["title"]).replace("\n", " ").replace("[", "(").replace("]", ")")
                    marker = "!" if row.get("provider") == "gitlab" else "#"
                    label = f"{row.get('repository', '')} {marker}{row['number']} {title}".strip()
                    print(f"{index}. [{label}]({row['url']}) - {size} lines, {row['changedFiles']} files")
                    print(f"   Base: {row['baseRefName']}; draft: {row['isDraft']}; review: {row['reviewDecision'] or 'none'}")
                    print(f"   Head: {row['headRefOid']}; inspect exact-head CI with --json.")
            return 0
        with exclusive(args.receipt):
            if args.group in ("pr", "mr") and args.operation == "rebase":
                result = prs.prepare(args.repo, args.number, args.old_base, args.worktree, args.receipt, remotes[0])
            elif args.group in ("pr", "mr"):
                result = prs.publish_pr(args.receipt, args.reviewed_head, arrays(read(args.checks)["commands"]))
            elif args.operation == "plan":
                result = recovery.plan(args.repo, args.spec, args.worktree, args.receipt, remotes[0])
            else:
                result = recovery.apply(args.receipt, arrays(read(args.checks)["commands"]))
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
