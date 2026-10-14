"""
Declare reusable collection command arguments without loading runtime services.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from . import collection_export as export_cli

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
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("setup", help="Install into Codex home and project secrets to an explicit private repository")
    install.add_argument("--repo", required=True)
    install.add_argument("--checkout", type=Path, default=Path.cwd())
    install.add_argument("--home", type=Path, default=Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser())
    install.add_argument("--key-dir", type=Path)
    install.add_argument(
        "--restore", action="store_true", help="Restore the encrypted collection into an empty local home using saved keys"
    )
    install.add_argument("--create", action="store_true", help="Create an independent private GitHub repository from a fresh library clone")
    sealing = commands.add_parser("seal", help="Validate, encrypt, and sign the current source collection; Git publication is separate")
    sealing.add_argument("--checkout", type=Path, required=True)
    sealing.add_argument("--source", type=Path, required=True)
    sealing.add_argument("--key-dir", type=Path, required=True)
    restoring = commands.add_parser("restore", help="Verify then decrypt sources or figures into a new local directory")
    restoring.add_argument("--checkout", type=Path, required=True)
    restoring.add_argument("--key-dir", type=Path, required=True)
    restoring.add_argument("--output", type=Path, required=True)
    restoring.add_argument("--figures", action="store_true")
    rebuilding = commands.add_parser("refresh", help="Trusted private main-branch CI entry point")
    rebuilding.add_argument("--checkout", type=Path, default=Path.cwd())
    commands.add_parser("schema", help="Print closed configuration and transport schemas")
    checking = commands.add_parser("check-storage", help="Verify local private working volumes; does not enable disk encryption")
    checking.add_argument("--path", type=Path, action="append", required=True)
    verification = commands.add_parser("verify", help="Verify encrypted sources and figures against independently pinned signing identity")
    verification.add_argument("--checkout", type=Path, default=Path.cwd())
    verification.add_argument("--signing-fingerprint", required=True, help="Trusted fingerprint retained separately from the artifact")
    verification.add_argument("--figures", action="store_true")
    inventory = commands.add_parser(
        "inventory", help="List current managed ciphertext digests; retained history and external storage are separate"
    )
    inventory.add_argument("--checkout", type=Path, default=Path.cwd())
    candidate = commands.add_parser("rotation-keys", help="Explicitly create/reuse a separate key backup and a private candidate JSON file")
    candidate.add_argument("--repo", required=True)
    candidate.add_argument("--key-dir", type=Path, required=True)
    candidate.add_argument("--rotate-by", required=True, help="Next rotation deadline, YYYY-MM-DD in UTC")
    candidate.add_argument("--output", type=Path, required=True)
    rotating = commands.add_parser("rotate", help="Prepare verified previous/current snapshots without modifying the live checkout")
    rotating.add_argument("--checkout", type=Path, required=True)
    rotating.add_argument("--key-dir", type=Path, required=True)
    rotating.add_argument("--candidate", type=Path, required=True, help="Private JSON file, never credentials on the command line")
    rotating.add_argument("--output", type=Path, required=True)
    promoting = commands.add_parser("promote-keys", help="Explicitly update existing primary Actions secrets after published rotation")
    promoting.add_argument("--checkout", type=Path, required=True)
    promoting.add_argument("--key-dir", type=Path, required=True)
    for command in ("prepare-refresh", "publish-refresh"):
        prepared = commands.add_parser(command, help="Trusted private main pipeline stage; publication requires verified preparation")
        prepared.add_argument("--checkout", type=Path, default=Path.cwd())
        prepared.add_argument("--output", type=Path, required=True)
    for command in ("seal-file", "restore-file"):
        managed = commands.add_parser(command, help="Explicitly manage one opaque file outside the source archive allowlist")
        managed.add_argument("--checkout", type=Path, required=True)
        managed.add_argument("--key-dir", type=Path, required=True)
        managed.add_argument("--name", required=True, help="Non-sensitive opaque identifier")
        managed.add_argument("--source" if command == "seal-file" else "--output", type=Path, required=True)
    export_cli.register(commands)
