"""
Compose release operations through Witful's lazy command builder.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from witful.commands.builder import Command, dispatch

if TYPE_CHECKING:
    from collections.abc import Sequence


def prepare_arguments(parser: argparse.ArgumentParser) -> None:
    """
    Declare local output for the read-only preparation operation.

    Args:
        parser (argparse.ArgumentParser): Fresh command-owned parser.

    Returns:
        None: Arguments are registered without running the operation.
    """
    parser.add_argument("--output", type=Path, required=True)


def notification_arguments(parser: argparse.ArgumentParser) -> None:
    """
    Declare explicit verification inputs and optional read-only notification preview.

    Args:
        parser (argparse.ArgumentParser): Fresh command-owned parser.

    Returns:
        None: Arguments are registered without accessing a release.
    """
    parser.add_argument("--built", type=Path, required=True)
    parser.add_argument("--download", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--fingerprint", required=True)
    parser.add_argument("--dry-run", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    """
    Compose shared identity inputs and independently owned executable leaves.

    Returns:
        argparse.ArgumentParser: Reusable hierarchy without importing SDK or verification runtimes.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), required=not os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--tag", default=os.environ.get("RELEASE_TAG"), required=not os.environ.get("RELEASE_TAG"))
    parser.add_argument("--source", default=os.environ.get("GITHUB_SHA"), required=not os.environ.get("GITHUB_SHA"))
    commands = parser.add_subparsers(required=True)
    Command(
        "prepare", "Write release notes and inventory locally without remote writes", prepare_arguments, f"{__package__}.feedback"
    ).register(commands)
    Command("notify", "Verify publication and send missing contributor comments", notification_arguments, f"{__package__}.report").register(
        commands
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """
    Parse once before loading the selected runtime and its credential-safe error boundary.

    Args:
        argv (Sequence[str] | None): Explicit arguments, or the process command line.

    Returns:
        int: Zero on success, two for invalid publication or incomplete reporting.
    """
    args = build_parser().parse_args(argv)
    from github import GithubException
    from jsonschema import ValidationError
    from requests.exceptions import RequestException

    try:
        return dispatch(args)
    except (OSError, ValueError, GithubException, RequestException, ValidationError, subprocess.SubprocessError):
        print(
            "Release reporting failed; inspect source, publication and access. No provider payload or credential was logged.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
