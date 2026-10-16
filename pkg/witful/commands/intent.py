"""
Declare hierarchical read-only discovery separately from explicit evidence publication and semantic review.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from witful.commands.builder import Command
from witful.commands.codegraph import common

if TYPE_CHECKING:
    import argparse


def query(parser: argparse.ArgumentParser) -> None:
    """
    Declare bounded read-only query inputs shared by discovery leaves.

    Args:
        parser (argparse.ArgumentParser): Owning leaf parser.

    Returns:
        None: No network, import of server dependencies or credential access occurs.
    """
    common(parser)
    parser.add_argument("value", nargs="?", default="")
    parser.add_argument("--view", choices=("both", "verified", "inferred"), default="both")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--required", action="append", default=[])
    parser.add_argument("--changed", action="append", default=[])
    parser.add_argument("--action", default="")
    parser.add_argument("--nodes", type=int, default=2000)
    parser.add_argument("--edges", type=int, default=8000)
    parser.add_argument("--tokens", type=int, default=8000)
    parser.add_argument("--bytes", type=int, default=16000)
    parser.add_argument("--elapsed-ms", type=int, default=10000)


def mutation(parser: argparse.ArgumentParser) -> None:
    """
    Read an explicit typed proposal through a pipe and require an exact publication predecessor.

    Args:
        parser (argparse.ArgumentParser): Publication or review leaf.

    Returns:
        None: Required operation IDs make retries stable; input comes from stdin only.
    """
    common(parser)
    parser.add_argument("--operation", required=True)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--expected")
    choice.add_argument("--initial", action="store_true")


def source(parser: argparse.ArgumentParser) -> None:
    """
    Require exact source identity and byte offsets for source reads.

    Args:
        parser (argparse.ArgumentParser): Source leaf.

    Returns:
        None: Source limits reuse the bounded discovery options.
    """
    query(parser)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--start", required=True, type=int)
    parser.add_argument("--end", required=True, type=int)


def command() -> Command:
    """
    Compose nested intent operations through the common recursive builder.

    Returns:
        Command: Complete portable CLI hierarchy with lazy runtime dispatch.
    """
    return Command(
        "intent",
        "Discover evidence-backed capabilities without executing them",
        children=(
            Command("draft", "Prepare unpublished candidates from a repertoire snapshot on stdin", query, "witful.intent.cli"),
            Command("find", "Find scoped capability assertions", query, "witful.intent.cli"),
            Command("explain", "Resolve exact evidence and counterevidence", query, "witful.intent.cli"),
            Command("coverage", "Inspect exact reading receipts", query, "witful.intent.cli"),
            Command("preflight", "Describe requirements without executing checks", query, "witful.intent.cli"),
            Command("affected", "Compute reverse invalidation", query, "witful.intent.cli"),
            Command("source", "Read exact admitted source bytes", source, "witful.intent.cli"),
            Command("publish", "Publish an encrypted candidate from stdin", mutation, "witful.intent.cli"),
            Command("review", "Append an authorized semantic review from stdin", mutation, "witful.intent.cli"),
        ),
    )
