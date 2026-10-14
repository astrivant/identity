"""
Declare reusable delivery command arguments without loading runtime services.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse


def configure(parser: argparse.ArgumentParser) -> None:
    """
    Compose this domain into the supplied parser.

    Args:
        parser (argparse.ArgumentParser): Standalone or parent-owned command parser.

    Returns:
        None: Arguments are registered without parsing or executing them.
    """
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Existing source checkout")
    parser.add_argument("--remote", action="append", help="Select REMOTE or PROVIDER:REMOTE; repeat for combined read-only inventories")
    groups = parser.add_subparsers(dest="group", required=True)
    pr = groups.add_parser("pr", aliases=["mr"]).add_subparsers(dest="operation", required=True)
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
