"""
Declare reusable completion command arguments without loading runtime services.
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
    parser.add_argument("--repo", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "check"):
        command = commands.add_parser(name)
        command.add_argument("--task", required=True)
        command.add_argument("--workspace", type=Path, action="append", default=[])
        command.add_argument("--output" if name == "plan" else "--input", type=Path, required=True)
        if name == "plan":
            command.add_argument("--replace", action="store_true", help="Discard previous attestations and capture a fresh plan")
    commands.add_parser("schema")
    for name in ("hook-config", "codex-hook"):
        command = commands.add_parser(name)
        command.add_argument("--identity", required=True)
