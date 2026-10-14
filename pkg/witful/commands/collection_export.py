"""
Register encrypted export arguments without loading export services.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse


def register(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """
    Register explicit export operations without changing collection installation or keys.

    Args:
        commands (argparse._SubParsersAction[argparse.ArgumentParser]): Parent collection command group.

    Returns:
        None: Three offline operations are available under collection.
    """
    exporting = commands.add_parser("export", help="Encrypt and sign current sealed records for yourself or a recipient")
    exporting.add_argument("--checkout", type=Path, help="Defaults to the installed setup receipt, then the working directory")
    exporting.add_argument("--key-dir", type=Path, help="Existing owner key backup; defaults to setup receipt or active environment keys")
    exporting.add_argument("--home", type=Path, default=Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser())
    exporting.add_argument("--recipient-key", type=Path, help="Trusted RSA public PEM; defaults to the active encryption key")
    exporting.add_argument("--output", type=Path, required=True, help="New export directory; no publication is performed")
    for name in ("verify-export", "restore-export"):
        command = commands.add_parser(name, help="Verify the complete bundle against the independently trusted sender")
        command.add_argument("--bundle", type=Path, required=True)
        command.add_argument("--signing-fingerprint", required=True)
        if name == "restore-export":
            command.add_argument("--private-key", type=Path, required=True, help="Recipient encrypted RSA PEM, never a signing key")
            command.add_argument("--password-file", type=Path, required=True, help="Private file containing exact password bytes")
            command.add_argument("--output", type=Path, required=True, help="New protected plaintext directory outside Git")
