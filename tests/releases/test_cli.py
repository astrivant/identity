"""
Keep release command help lazy and preserve shared inputs through composed leaves.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from release.cli import build_parser
from witful.commands.builder import Command


def test_help_does_not_load_release_runtimes() -> None:
    """
    Construct and print help in a fresh interpreter without initializing SDK or verification code.

    Returns:
        None: Public command composition stays independent from runtime imports.
    """
    source = (
        "import sys; from scripts.release.cli import build_parser; "
        "build_parser().print_help(); "
        "assert not {'github', 'scripts.release.feedback', 'scripts.release.report', "
        "'scripts.release.verification'}.intersection(sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    assert "prepare" in result.stdout and "notify" in result.stdout


def test_shared_release_identity_survives_both_command_builders() -> None:
    """
    Retain explicit repository, tag and source while each leaf owns its own arguments.

    Returns:
        None: Both leaves reuse the canonical Command contract with distinct runtimes.
    """
    parser = build_parser()
    shared = ["--repo", "example/project", "--tag", "v1.1.0", "--source", "a" * 40]
    prepared = parser.parse_args([*shared, "prepare", "--output", "preview"])
    notified = parser.parse_args(
        [
            *shared,
            "notify",
            "--built",
            "dist",
            "--download",
            "download",
            "--receipt",
            "receipt.json",
            "--fingerprint",
            "b" * 64,
            "--dry-run",
        ]
    )
    for arguments in (prepared, notified):
        assert (arguments.repo, arguments.tag, arguments.source) == ("example/project", "v1.1.0", "a" * 40)
        assert isinstance(arguments.handler, Command)
    assert prepared.handler.module != notified.handler.module
    assert prepared.output == Path("preview") and notified.dry_run
