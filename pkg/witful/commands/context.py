"""
Declare reusable context command arguments without loading runtime services.
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
    parser.add_argument("--repo", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("schema")
    commands.add_parser("snapshot")
    for name in ("plan", "resolve", "check"):
        command = commands.add_parser(name)
        command.add_argument("--mapping", type=Path, required=True)
        command.add_argument("--descriptor", type=Path, required=True)
        command.add_argument(
            "--observed-at", type=int, required=True, help="Original source-snapshot observation epoch, never renewed by a check"
        )
        command.add_argument("--workspace", type=Path, action="append", default=[])
        command.add_argument("--decisions", type=Path)
        if name == "check":
            command.add_argument("--input", type=Path, required=True)
            command.add_argument(
                "--context-present", action="store_true", help="Attest exact loaded text is still present in this runtime context"
            )
        else:
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--replace", action="store_true")
