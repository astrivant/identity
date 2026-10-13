"""
Expose bounded PR and recovery helpers without treating chat command mentions as execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING

from . import prs, recovery
from .common import arrays, exclusive, read

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run the selected explicit delivery operation using existing Git and GitHub authentication.

    Args:
        argv (Sequence[str] | None): Argument vector; None reads the process arguments.

    Returns:
        int: Zero after the requested stage succeeds; parser errors exit with status two.
    """
    parser = argparse.ArgumentParser(description="Reviewable PR rebases and resumable small-first Git recovery")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Existing source checkout")
    groups = parser.add_subparsers(dest="group", required=True)
    pr = groups.add_parser("pr").add_subparsers(dest="operation", required=True)
    show = pr.add_parser("show", help="Read-only, dependency-first review order")
    show.add_argument("--dependencies", type=Path, help="Reviewed extra dependencies as {PR: [prerequisites]}")
    show.add_argument("--json", action="store_true", help="Include full metadata and raw check evidence")
    rebase = pr.add_parser("rebase", help="Prepare one isolated signed rebase; never push")
    rebase.add_argument("--number", type=int, required=True)
    rebase.add_argument("--old-base", required=True, help="Original replay boundary captured before parent rewrites")
    rebase.add_argument("--worktree", type=Path, required=True)
    rebase.add_argument("--receipt", type=Path, required=True)
    publish = pr.add_parser("publish", help="Validate and publish a reviewed exact candidate")
    publish.add_argument("--receipt", type=Path, required=True)
    publish.add_argument("--reviewed-head", required=True)
    publish.add_argument("--checks", type=Path, required=True, help='JSON object: {"commands": [["executable", "argument"]]}')
    recover = groups.add_parser("recovery").add_subparsers(dest="operation", required=True)
    plan = recover.add_parser("plan", help="Sort coherent source-file batches without pushing")
    plan.add_argument("--spec", type=Path, required=True)
    plan.add_argument("--worktree", type=Path, required=True)
    plan.add_argument("--receipt", type=Path, required=True)
    apply = recover.add_parser("apply", help="Publish or resume reviewed batches after inspecting branch CI effects")
    apply.add_argument("--receipt", type=Path, required=True)
    apply.add_argument("--checks", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.group == "pr" and args.operation == "show":
            rows = prs.inventory(args.repo, read(args.dependencies) if args.dependencies else {})
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                for index, row in enumerate(rows, 1):
                    size = prs.number(row["additions"]) + prs.number(row["deletions"])
                    title = str(row["title"]).replace("\n", " ").replace("[", "(").replace("]", ")")
                    print(f"{index}. [#{row['number']} {title}]({row['url']}) - {size} lines, {row['changedFiles']} files")
                    print(f"   Base: {row['baseRefName']}; draft: {row['isDraft']}; review: {row['reviewDecision'] or 'none'}")
                    print(f"   Head: {row['headRefOid']}; inspect exact-head CI with --json.")
            return 0
        with exclusive(args.receipt):
            if args.group == "pr" and args.operation == "rebase":
                result = prs.prepare(args.repo, args.number, args.old_base, args.worktree, args.receipt)
            elif args.group == "pr":
                result = prs.publish_pr(args.receipt, args.reviewed_head, arrays(read(args.checks)["commands"]))
            elif args.operation == "plan":
                result = recovery.plan(args.repo, args.spec, args.worktree, args.receipt)
            else:
                result = recovery.apply(args.receipt, arrays(read(args.checks)["commands"]))
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, KeyError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
