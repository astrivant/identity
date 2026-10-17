"""
Verify orchestration rejects source drift and missing coverage before producing publication data.
"""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING

import pytest
from test_matrix import cli
from test_matrix.core import plan
from test_matrix.models import Report, Result, Settings, State, write

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


def test_fanin_binds_sources_and_requires_each_coverage_file(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Exercise the actual fan-in command's artifact boundary and recovery after missing input.

    Args:
        tmp_path (Path): Disposable run root.
        monkeypatch (MonkeyPatch): Supply synthetic CI context and an explicit output directory.

    Returns:
        None: Missing coverage or foreign source fails before publication; complete input succeeds.
    """
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    for key, value in {
        "GITHUB_REPOSITORY": "example/project",
        "GITHUB_SHA": "a" * 40,
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
    }.items():
        monkeypatch.setenv(key, value)
    selected = plan(["test_a", "test_b"], State("scope"), Settings(), "example/project", "a" * 40, "123-1", time.time() - 10)
    write(tmp_path / "plan.json", selected)
    digest = hashlib.sha256((tmp_path / "plan.json").read_bytes()).hexdigest()
    report = Report(digest, 0, 0, 2.0, {"test_a": Result(1.0, "passed"), "test_b": Result(1.0, "passed")})
    write(tmp_path / "shards/worker/report.json", report)
    with pytest.raises(ValueError, match="raw coverage"):
        cli.finish()
    assert not (tmp_path / "publication.json").exists()
    (tmp_path / "shards/worker/.coverage.0").write_bytes(b"fixture; coverage combine validates the database separately")
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    with pytest.raises(ValueError, match="another source"):
        cli.finish()
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    cli.finish()
    assert (tmp_path / "publication/.github/metrics/tests/123-1.json").is_file()
    assert (tmp_path / "publication/docs/assets/test-convergence.svg").is_file()
