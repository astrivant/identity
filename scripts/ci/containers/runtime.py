"""
Verify the runtime contract inside a built image using synthetic temporary files.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from importlib.resources import files
from importlib.util import find_spec
from pathlib import Path

import witful


def verify(target: str) -> None:
    """
    Assert runtime ownership, packaged resources and target-specific installation boundaries.

    Args:
        target (str): The production or development image selected by the host driver.

    Returns:
        None: All checks pass, or an assertion reports the broken image contract.
    """
    assert os.getuid() == os.getgid() == 10001, "The runtime must be unprivileged."
    assert Path("/proc/1/comm").read_text().strip() == "tini", "Tini must own PID 1."
    assert sys.prefix == "/opt/witful", "The application must use its own environment."
    assert files("witful").joinpath("sql/postgres/life/schema.sql").is_file(), "The wheel must retain SQL resources."

    # These paths are writable in normal development and the read-only production test profile.
    for directory in (Path.cwd(), Path(os.environ["TMPDIR"]), Path(os.environ["MPLCONFIGDIR"]), Path(os.environ["XDG_CACHE_HOME"])):
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            assert Path(temporary).stat().st_mode & 0o777 == 0o700
            (Path(temporary) / "synthetic.txt").write_text("container contract\n")

    assert witful.__file__ is not None
    source = Path(witful.__file__).resolve()
    if target == "production":
        assert source.is_relative_to(Path(sys.prefix)), "Production must load the built wheel."
        assert not Path("/build").exists(), "Build sources must stay out of production."
        assert not Path("/opt/poetry").exists(), "Poetry must stay out of production."
        assert not os.access(sys.prefix, os.W_OK), "The runtime user must not modify installed dependencies."
        for module in ("pytest", "ruff", "mypy", "poetry", "agent_broker"):
            assert find_spec(module) is None, f"Development/server dependency leaked into production: {module}"
    else:
        assert source.is_relative_to("/build/pkg/witful"), "Development must load editable source, not the wheel."
        assert find_spec("pytest") is not None, "Development must include the locked test tools."
        assert shutil.which("poetry") == "/opt/poetry/bin/poetry", "Development must expose its isolated Poetry CLI."
        assert os.access(sys.prefix, os.W_OK), "Development must permit local dependency work."
        cache = Path(os.environ["POETRY_CACHE_DIR"])
        cache.mkdir(parents=True, exist_ok=True)
        assert os.access(cache, os.W_OK), "Development must own its Poetry download cache."


def main() -> int:
    """
    Select the declared target and execute its in-container checks.

    Returns:
        int: Zero after successful verification; assertion failures remain visible.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=("production", "development"))
    arguments = parser.parse_args()
    verify(arguments.target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
