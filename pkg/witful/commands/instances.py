"""
Declare reusable instances command arguments without loading runtime services.
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
    creation = commands.add_parser("start", help="Reuse a known boundary or record a new observed instance")
    creation.add_argument("--boundary-id", required=True)
    creation.add_argument("--boundary-kind", choices=("runtime", "logical-session"), required=True)
    for name in (
        "session-id",
        "served-model",
        "model-evidence",
        "requested-model",
        "template-revision",
        "parent-instance-id",
        "predecessor-instance-id",
    ):
        creation.add_argument("--" + name)
    creation.add_argument("--coverage", choices=("incomplete", "complete"), default="incomplete")
    creation.add_argument("--coverage-source")
    for command in ("reconcile", "task", "audit", "observe", "stop"):
        operation = commands.add_parser(command)
        operation.add_argument("--instance-id", required=True)
        operation.add_argument("--operation-id", required=True)
        if command == "reconcile":
            operation.add_argument("--coverage", choices=("incomplete", "complete"), required=True)
            operation.add_argument("--coverage-source")
        if command == "task":
            operation.add_argument("--task-id", required=True)
            operation.add_argument("--status", choices=("pending", "running", "blocked", "succeeded", "failed", "cancelled"), required=True)
            operation.add_argument("--summary", required=True)
            operation.add_argument("--source", required=True)
            operation.add_argument("--previous", help="Exact preceding task event ID, required for updates")
        if command == "audit":
            operation.add_argument("--action", required=True)
            operation.add_argument("--outcome", default="unknown")
            operation.add_argument("--request-id")
            operation.add_argument("--trace-id")
            operation.add_argument("--span-id")
    for command in ("guard", "resource"):
        operation = commands.add_parser(command)
        operation.add_argument("--instance-id", required=True)
    for command in ("status", "check", "schemas", "logs"):
        commands.add_parser(command)
    render = commands.add_parser("build")
    render.add_argument("--output-dir", type=Path, default=Path("docs/assets"))
    render.add_argument("--limit", type=int, default=8)
