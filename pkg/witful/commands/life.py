"""
Declare reusable life command arguments without loading runtime services.
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
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("schemas", help="Generate schemas from the audit models")
    commands.add_parser("check", help="Validate the complete audit, snapshots, and committed schemas")
    record = commands.add_parser("record", help="Append a reviewed decision JSON document, or its explicit revision")
    record.add_argument("--input", type=Path, required=True)
    record.add_argument("--source-revision", help="Import knowledge inputs from an existing Git revision")
    show = commands.add_parser("show", help="Inspect current choices or their retained history")
    show.add_argument("--key")
    show.add_argument("--history", action="store_true")
    build = commands.add_parser("build", help="Render today's view of the decision history without rewriting source records")
    build.add_argument("--output-dir", type=Path, default=Path("docs/assets"))
    replay = commands.add_parser("replay", help="Reconstruct a journal prefix and its saved knowledge plots")
    replay.add_argument("--through", help="Inclusive last event ID; omitted means the complete journal")
    replay.add_argument("--output-dir", type=Path, default=Path(".cache/life-replay"))
    replay.add_argument("--allow-renderer-drift", action="store_true")
    replay.add_argument("--from-database", action="store_true", help="Use the PostgreSQL archive without reading current source journals")
    commands.add_parser("seed", help="Seed WITFUL_DATABASE_URL with the validated local audit and replay snapshots")
