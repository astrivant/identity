"""
Declare reusable registry command arguments without loading runtime services.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from witful.registry.constants import DEFAULT_TTL

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
    parser.add_argument("names", nargs="*")
    parser.add_argument("--stdin", action="store_true", help="Read one additional candidate per line, skipping blank lines")
    parser.add_argument("--cache-dir", type=Path, default=Path.home() / ".cache" / "registry-names")
    parser.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL)
    parser.add_argument("--timeout-seconds", type=int, default=10)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--refresh", action="store_true", help="Recheck before publication; active cooldowns still apply")
    modes.add_argument("--offline", action="store_true", help="Use only unexpired observations without making requests")
    parser.add_argument("--only-unregistered", action="store_true", help="Print just missing project names; this does not reserve them")
