"""
Declare reusable checkpoints command arguments without loading runtime services.
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
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--namespace", default=os.environ.get("WITFUL_DATABASE_NAMESPACE", "default"))
    parser.add_argument("--database", type=Path, help="Local SQLite mirror, default .witful/checkpoints.sqlite3")
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("record", help="Snapshot reviewed evidence at a project's committed HEAD")
    capture.add_argument("--project", type=Path, required=True)
    capture.add_argument("--project-id", required=True, help="Stable chosen alias; remote URLs and machine paths are never inferred")
    commands.add_parser("check", help="Validate the journal without creating data or plots")
    commands.add_parser("schemas", help="Generate the authoritative checkpoint schema")
    commands.add_parser("sync", help="Seed the SQLite mirror, or explicitly selected WITFUL_DATABASE_URL")
    difference = commands.add_parser("diff", help="Compare two snapshots, defaulting to the last two checkpoints")
    difference.add_argument("--before")
    difference.add_argument("--after")
    difference.add_argument("--from-database", action="store_true")
    render = commands.add_parser("build", help="Compute all differences and refresh recent-project plots")
    render.add_argument("--from-database", action="store_true")
    render.add_argument("--output-dir", type=Path, default=Path("docs/assets"))
    render.add_argument("--limit", type=int, default=8)
