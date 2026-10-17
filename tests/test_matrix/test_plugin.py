"""
Verify actual pytest/xdist collection and fan-in, including drift and skipped cases.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from test_matrix.core import aggregate, plan
from test_matrix.models import Report, Settings, State, load, write


def test_real_pytest_workers_cover_the_frozen_plan(tmp_path: Path) -> None:
    """
    Exercise the real plugin across independently launched matrix workers and reject collection drift.

    Args:
        tmp_path (Path): Isolated source, plan and report locations.

    Returns:
        None: Every case appears once, the skip is explicit and a changed collection cannot pass.
    """
    root = Path(__file__).resolve().parents[2]
    shutil.copy(Path(__file__).parent / "fixtures/cases.py", tmp_path / "test_cases.py")
    env = {**os.environ, "PYTHONPATH": str(root / "scripts/ci")}
    common = [sys.executable, "-m", "pytest", "-c", "/dev/null", "-p", "test_matrix.plugin", "-q"]
    result = subprocess.run(
        [*common, "--collect-only", "--matrix-collect=nodes.json"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr
    nodes = json.loads((tmp_path / "nodes.json").read_bytes())
    selected = plan(nodes, State("scope"), Settings(threshold=2), "example/project", "a" * 40, "1-1")
    write(tmp_path / "plan.json", selected)
    reports = []
    for index in range(len(selected.partitions)):
        result = subprocess.run(
            [*common, "-n", "2", "--matrix-plan=plan.json", f"--matrix-shard={index}", f"--matrix-report=report-{index}.json"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        reports.append(load(tmp_path / f"report-{index}.json", Report))
    _, sample = aggregate(selected, hashlib.sha256((tmp_path / "plan.json").read_bytes()).hexdigest(), reports)
    assert sample.tests == 4 and sample.skipped == 1
    result = subprocess.run(
        [*common, "-k", "not 4", "--matrix-plan=plan.json", "--matrix-report=drift.json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0 and "collection differs" in result.stderr
