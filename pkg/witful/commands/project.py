"""
Declare reusable initialization command arguments without loading runtime services.
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
    parser.add_argument("path", type=Path)
