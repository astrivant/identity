"""
Expose explicit local installation, encrypted publication, restoration, and trusted CI refresh.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidTag, UnsupportedAlgorithm
from jsonschema import ValidationError

from witful.collection.install import setup
from witful.collection.models import Config, Envelope
from witful.collection.operations import refresh, restore, seal
from witful.knowledge.contracts import schema

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run one bounded operation and redact errors that may contain private source values.

    Args:
        argv (Sequence[str] | None): Explicit arguments or process arguments.

    Returns:
        int: Zero on success; two for failed validation, cryptography, tooling, or I/O.
    """
    parser = argparse.ArgumentParser(description=__doc__)
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
    args = parser.parse_args(argv)
    os.umask(0o077)

    try:
        if args.command == "schema":
            print(json.dumps({"config": schema(Config), "envelope": schema(Envelope)}, indent=2))
        elif args.command == "setup":
            directory = (
                args.key_dir
                or Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
                / "witful/collections"
                / hashlib.sha256(args.repo.lower().encode()).hexdigest()[:24]
            )
            setup(args.repo, args.checkout, args.home, directory, create=args.create, restore_existing=args.restore)
        elif args.command == "seal":
            seal(args.checkout, args.source, args.key_dir)
            print("Encrypted source and signature updated; commit and push the named collection files.")
        elif args.command == "restore":
            restore(args.checkout, args.key_dir, args.output, "figures" if args.figures else "sources")
            print("Verified collection restored into the selected new directory.")
        else:
            refresh(args.checkout)
            print("Current collection figures regenerated and encrypted; no source values were logged.")
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, InvalidTag, UnsupportedAlgorithm, ValidationError):
        parser.exit(
            2,
            "Collection operation failed. Check private repository access, key backups, trust pins, "
            "and source validation locally; private diagnostics were withheld.\n",
        )

    return 0
