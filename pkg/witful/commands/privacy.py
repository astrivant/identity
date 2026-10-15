"""
Declare reusable privacy command arguments without loading runtime services.
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
    parser.add_argument("command", choices=["scan"])
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--staged", action="store_true", help="Inspect the complete index, not unstaged working-tree replacements")
    parser.add_argument("--require-complete", action="store_true", help="Exit 2 if any selected content cannot be inspected as text")
    parser.add_argument(
        "--terms-file", type=Path, default=os.environ.get("WITFUL_PII_TERMS_FILE"), help="Private UTF-8 literals, one per line"
    )
