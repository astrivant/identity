"""
Declare reusable reflection command arguments without loading runtime services.
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
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    commands.add_parser("schema")
    planning = commands.add_parser("plan")
    planning.add_argument("--history-repo", type=Path)
    planning.add_argument("--output", type=Path, default=Path(".cache/reflection-plan.json"))
    recording = commands.add_parser("record")
    recording.add_argument("--input", type=Path, required=True, help="JSON array of reviewed Assessment objects")
    recording.add_argument("--history-repo", type=Path)
    for name in ("build", "example"):
        rendering = commands.add_parser(name)
        rendering.add_argument("--output-dir", type=Path, default=Path("docs/assets"))
