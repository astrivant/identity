"""
Declare reusable knowledge command arguments without loading runtime services.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse


def configure(parser: argparse.ArgumentParser) -> argparse._SubParsersAction[argparse.ArgumentParser]:
    """
    Compose this domain into the supplied parser.

    Args:
        parser (argparse.ArgumentParser): Standalone or parent-owned command parser.

    Returns:
        argparse._SubParsersAction[argparse.ArgumentParser]: Root command group for additional domain registration.
    """
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Existing knowledge checkout; defaults to the current directory")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="Validate journal, source schemas, hierarchy, and every application")
    build = commands.add_parser("build", help="Regenerate schemas, graph export, and README plots")
    build.add_argument("--output-dir", type=Path, default=Path("docs/assets"))
    show = commands.add_parser("show", help="List concept IDs or inspect one concept and its recorded usage")
    show.add_argument("identifier", nargs="?")
    record = commands.add_parser("record", help="Append a sourced application or a complete revised observation")
    record.add_argument("--task", required=True)
    record.add_argument("--discipline", required=True)
    record.add_argument("--concept", action="append", required=True)
    record.add_argument("--outcome", choices=["unassessed", "verified", "unsuccessful"], default="unassessed")
    record.add_argument("--evidence", required=True)
    return commands
