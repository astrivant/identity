"""
Declare reusable storage command arguments without loading runtime services.
"""

from __future__ import annotations

import os
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
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("WITFUL_HOME", Path.cwd() / ".witful")))
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--namespace", default=os.environ.get("WITFUL_DATABASE_NAMESPACE", "default"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sync", help="Synchronize the selected lesson index from the versioned export")
    commands.add_parser("status", help="Show locations, provenance count, and retained history size")
    commands.add_parser("check", help="Validate JSONL and SQL in a temporary database without updating runtime state")
    lookup = commands.add_parser("search", help="Find relevant lessons; terms are literal words")
    lookup.add_argument("terms")
    lookup.add_argument("--history", action="store_true")
    lookup.add_argument("--limit", type=int, default=10)
    add = commands.add_parser("add", help="Append sourced guidance or a correction; Git publication is separate")
    add.add_argument("--topic", required=True)
    add.add_argument("--lesson", required=True)
    add.add_argument("--source", required=True)
    add.add_argument("--supersedes")
