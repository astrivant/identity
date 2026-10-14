"""
Declare reusable sleeves command arguments without loading runtime services.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def configure(parser: argparse.ArgumentParser) -> None:
    """
    Compose this domain into the supplied parser.

    Args:
        parser (argparse.ArgumentParser): Standalone or parent-owned command parser.

    Returns:
        None: Arguments are registered without parsing or executing them.
    """
    commands = parser.add_subparsers(dest="command", required=True)
    starting = commands.add_parser("start", help="Create and back up a private isolated session from current remote main")
    starting.add_argument("--repo", type=Path, required=True)
    starting.add_argument("--directory", type=Path, required=True)
    starting.add_argument("--name", required=True)
    starting.add_argument("--base", default="main")
    starting.add_argument("--remote", default="origin")
    starting.add_argument("--key-dir", type=Path)
    checkpoint = commands.add_parser("checkpoint", help="Validate, sign, and push named changes to this sleeve")
    checkpoint.add_argument("--repo", type=Path, default=Path.cwd())
    checkpoint.add_argument("--paths", nargs="*", default=[])
    checkpoint.add_argument("--message", default="Checkpoint identity sleeve")
    finishing = commands.add_parser("finish", help="Reconcile and close only after remote integration is verified")
    finishing.add_argument("--repo", type=Path, default=Path.cwd())
    finishing.add_argument("--pull-request", action="store_true", help="Propose review instead of directly pushing the integration branch")
    supervised = commands.add_parser("run", help="Supervise a workload and checkpoint/reconcile on exit or termination")
    supervised.add_argument("--repo", type=Path, default=Path.cwd())
    supervised.add_argument("--paths", nargs="*", default=[])
    supervised.add_argument("--shutdown-seconds", type=float, default=90)
    supervised.add_argument("--stop-seconds", type=float, default=10)
    supervised.add_argument("--pull-request", action="store_true")
    supervised.add_argument("workload", nargs=argparse.REMAINDER)
    for name in ("status", "guard", "backup"):
        descriptions = {
            "status": "List local sleeves",
            "guard": "Fail normal session shutdown until closed",
            "backup": "Push existing sleeve commits without staging incomplete source edits",
        }
        command = commands.add_parser(name, help=descriptions[name])
        command.add_argument("--repo", type=Path, default=Path.cwd())
    commands.add_parser("schema", help="Print the closed local receipt schema")
