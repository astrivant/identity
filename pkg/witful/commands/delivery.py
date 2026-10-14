"""
Declare the delivery tree without loading provider or Git runtimes.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .builder import Command

if TYPE_CHECKING:
    import argparse


def configure(parser: argparse.ArgumentParser) -> None:
    """
    Reuse the complete delivery tree for a standalone entrypoint.

    Args:
        parser (argparse.ArgumentParser): Fresh standalone parser.

    Returns:
        None: Local options and all command tiers are registered.
    """
    command().populate(parser)


def command() -> Command:
    """
    Describe delivery groups and operations with the recursive command contract.

    Returns:
        Command: A reusable tree with existing aliases and namespace fields.
    """
    runtime = "witful.delivery.cli"
    return Command(
        "delivery",
        "Review and prepare PRs and MRs",
        _options,
        destination="group",
        children=(
            Command(
                "pr",
                "Review and prepare pull or merge requests",
                aliases=("mr",),
                destination="operation",
                children=(
                    Command("show", "Read-only, dependency-first review order", _show, runtime),
                    Command("rebase", "Prepare one isolated signed rebase; never push", _rebase, runtime),
                    Command("publish", "Validate and publish a reviewed exact candidate", _publish, runtime),
                ),
            ),
            Command(
                "recovery",
                "Plan and publish reviewed recovery batches",
                destination="operation",
                children=(
                    Command("plan", "Sort coherent source-file batches without pushing", _plan, runtime),
                    Command("apply", "Publish or resume reviewed batches after inspecting branch CI effects", _apply, runtime),
                ),
            ),
        ),
    )


def _options(parser: argparse.ArgumentParser) -> None:
    """
    Declare options owned by delivery rather than repeating defaults on every leaf.

    Args:
        parser (argparse.ArgumentParser): Delivery parser.

    Returns:
        None: Repository and remote selectors are registered.
    """
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Existing source checkout")
    parser.add_argument("--remote", action="append", help="Select REMOTE or PROVIDER:REMOTE; repeat for combined read-only inventories")


def _show(parser: argparse.ArgumentParser) -> None:
    """
    Declare read-only inventory inputs.

    Args:
        parser (argparse.ArgumentParser): Show operation parser.

    Returns:
        None: Dependency and output options are registered.
    """
    parser.add_argument("--dependencies", type=Path, help="Reviewed extra dependencies as {PR: [prerequisites]}")
    parser.add_argument("--json", action="store_true", help="Include full metadata and raw check evidence")


def _rebase(parser: argparse.ArgumentParser) -> None:
    """
    Declare the exact source boundary and isolated rebase destination.

    Args:
        parser (argparse.ArgumentParser): Rebase operation parser.

    Returns:
        None: Required preparation inputs are registered.
    """
    parser.add_argument("--number", type=int, required=True)
    parser.add_argument("--old-base", required=True, help="Original replay boundary captured before parent rewrites")
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)


def _publish(parser: argparse.ArgumentParser) -> None:
    """
    Declare the reviewed candidate and its publication evidence.

    Args:
        parser (argparse.ArgumentParser): Publish operation parser.

    Returns:
        None: Required publication inputs are registered.
    """
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--reviewed-head", required=True)
    parser.add_argument("--checks", type=Path, required=True, help='JSON object: {"commands": [["executable", "argument"]]}')


def _plan(parser: argparse.ArgumentParser) -> None:
    """
    Declare local recovery planning inputs.

    Args:
        parser (argparse.ArgumentParser): Plan operation parser.

    Returns:
        None: Required plan inputs are registered.
    """
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)


def _apply(parser: argparse.ArgumentParser) -> None:
    """
    Declare the reviewed recovery receipt and checks.

    Args:
        parser (argparse.ArgumentParser): Apply operation parser.

    Returns:
        None: Required recovery inputs are registered.
    """
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--checks", type=Path, required=True)
