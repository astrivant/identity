"""
Keep boundary checks adjacent to source-link linting and protect the invoking Git index.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml


def test_boundary_hook_order() -> None:
    """
    Require the same unconditional boundary guard in commit, push and hosted checks.

    Returns:
        None: Hook filtering and CI refactors cannot silently omit the known regression checks.
    """
    root = Path(__file__).parents[2]
    configuration: object = yaml.safe_load((root / ".pre-commit-config.yaml").read_text())
    assert isinstance(configuration, dict)
    hooks = [hook for repo in configuration["repos"] for hook in repo["hooks"]]
    index = next(index for index, hook in enumerate(hooks) if hook["id"] == "documentation-source-links")
    guard = hooks[index + 1]
    assert guard["id"] == "documentation-source-link-contracts"
    assert guard["entry"] == "python scripts/documentation/check-source-link-contracts.py"
    assert guard["always_run"] is True and guard["pass_filenames"] is False
    assert guard["stages"] == ["pre-commit", "pre-push", "manual"]
    assert not {"files", "types", "types_or", "exclude", "exclude_types"} & guard.keys()
    workflow: object = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
    assert isinstance(workflow, dict)
    commands = [step["run"] for step in workflow["jobs"]["lint"]["steps"] if "run" in step]
    index = commands.index("pre-commit run documentation-source-links --all-files")
    assert commands[index + 1] == "pre-commit run documentation-source-link-contracts --all-files"


def test_hook_fixture_preserves_caller_index(tmp_path: Path) -> None:
    """
    Run the real filesystem regression with inherited Git routing toward a sentinel repository.

    Args:
        tmp_path (Path): Disposable caller repository and scratch directory.

    Returns:
        None: The nested test operates in its own fixture and leaves the caller's index unchanged.
    """
    root = Path(__file__).parents[2]
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / "sentinel").write_text("Preserve the invoking worktree.\n")
    subprocess.run(["git", "add", "sentinel"], cwd=tmp_path, check=True)
    index = tmp_path / ".git/index"
    before = index.read_bytes()
    environment = {
        **os.environ,
        "GIT_DIR": str(tmp_path / ".git"),
        "GIT_WORK_TREE": str(tmp_path),
        "GIT_INDEX_FILE": str(index),
    }
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-n", "0", "-q", "tests/documentation/test_source_links.py::test_byte_budget_and_symlink"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert index.read_bytes() == before
    assert (tmp_path / "sentinel").read_text() == "Preserve the invoking worktree.\n"
