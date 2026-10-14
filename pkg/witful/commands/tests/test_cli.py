"""
Preserve parser hierarchy, help, domain errors and lightweight dispatch through the public entrypoint.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from witful.cli import build_parser, main
from witful.storage.cli import main as lessons_main

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import CaptureFixture


@pytest.mark.parametrize("command", ["delivery", "context", "completion", "collection", "sleeve", "lessons", "life", "registry"])
def test_domain_help_is_composed(command: str, capsys: CaptureFixture[str]) -> None:
    """
    Expose nested command help without invoking runtime operations.

    Args:
        command (str): Registered public domain.
        capsys (CaptureFixture[str]): Capture generated help.

    Returns:
        None: The root hierarchy handles help with a successful exit.
    """
    with pytest.raises(SystemExit) as result:
        main([command, "--help"])
    assert result.value.code == 0
    assert command in capsys.readouterr().out


def test_root_and_standalone_lesson_status_agree(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """
    Retain selected collection paths and domain status through either entrypoint.

    Args:
        tmp_path (Path): Synthetic collection and runtime index.
        capsys (CaptureFixture[str]): Captured JSON evidence.

    Returns:
        None: Both entrypoints execute identical parsed arguments and return source counts.
    """
    (tmp_path / "lessons.jsonl").touch()
    arguments = ["--repo", str(tmp_path), "--home", str(tmp_path / "runtime"), "status"]
    assert main(["lessons", *arguments]) == 0
    combined = json.loads(capsys.readouterr().out)
    assert lessons_main(arguments) == 0
    assert json.loads(capsys.readouterr().out) == combined
    assert combined["repository"] == str(tmp_path)


def test_legacy_knowledge_commands_and_mr_alias_parse(tmp_path: Path) -> None:
    """
    Preserve legacy knowledge syntax and route both request aliases through one hierarchy.

    Args:
        tmp_path (Path): Explicit selected checkout.

    Returns:
        None: Root and nested arguments retain their intended ownership.
    """
    parser = build_parser()
    knowledge = parser.parse_args(["--repo", str(tmp_path), "show"])
    assert knowledge.repo == tmp_path and knowledge.command == "show"
    for alias in ("pr", "mr"):
        args = parser.parse_args(["delivery", "--remote", "github:origin", "--remote", "gitlab:mirror", alias, "show", "--json"])
        assert args.remote == ["github:origin", "gitlab:mirror"] and args.operation == "show" and args.json
    with pytest.raises(SystemExit) as result:
        main(["delivery", "mr", "rebase"])
    assert result.value.code == 2


def test_help_and_lesson_lookup_do_not_load_analytics_or_provider_sdks() -> None:
    """
    Check the import boundary in a fresh interpreter rather than trusting an already loaded test process.

    Returns:
        None: Composing and invoking lightweight help never imports analytics or provider runtime modules.
    """
    program = """
import sys
from witful.cli import main
try:
    main(['lessons', '--help'])
except SystemExit as result:
    assert result.code == 0
assert not {'matplotlib', 'networkx', 'github', 'gitlab', 'witful.knowledge.cli'} & sys.modules.keys()
"""
    result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
