"""
Keep installed third-party Python outside the project's docstring ownership boundary.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("defect", ["none", "layout", "types"])
def test_docstring_hooks_check_owned_files_only(tmp_path: Path, defect: str) -> None:
    """
    Reject owned violations while ignoring Python shipped inside npm dependencies.

    Args:
        tmp_path (Path): Temporary repository containing owned and vendored fixtures.
        defect (str): Optional owned layout or argument-type violation.

    Returns:
        None: Ignored dependency files never suppress checks of owned sources.
    """
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    selected = [hook for hook in config["repos"][0]["hooks"] if hook["id"] in {"docstrings", "typed-docstrings"}]
    assert len(selected) == 2
    (tmp_path / ".pre-commit-config.yaml").write_text(yaml.safe_dump({"repos": [{"repo": "local", "hooks": selected}]}))
    (tmp_path / "pyproject.toml").write_text((ROOT / "pyproject.toml").read_text())
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    dependency = tmp_path / "scripts/documentation/node_modules/vendor"
    dependency.mkdir(parents=True)
    (dependency / "fixture.py").write_text("def undocumented():\n    return 1\n")
    source = "\n".join(
        [
            '"""',
            "Exercise the owned contract.",
            '"""',
            "",
            "def count(value: int) -> int:",
            '    """',
            "    Return the supplied count.",
            "",
            "    Args:",
            "        value (int): Supplied count.",
            "",
            "    Returns:",
            "        int: The same count.",
            '    """',
            "    return value",
            "",
        ]
    )

    if defect == "layout":
        source = "def count(value: int) -> int:\n    return value\n"
    elif defect == "types":
        source = source.replace("value (int):", "value (str):")

    (tmp_path / "owned.py").write_text(source)
    # The fixture owns its index even when a caller is validating a separate candidate.
    environment = {key: value for key, value in os.environ.items() if key != "GIT_INDEX_FILE"}
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], env=environment, check=True)
    subprocess.run(["git", "add", "owned.py"], cwd=tmp_path, env=environment, check=True)
    result = subprocess.run(
        ["pre-commit", "run", "--all-files"],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert (result.returncode == 0) == (defect == "none"), result.stdout + result.stderr
    assert "node_modules" not in result.stdout + result.stderr
