"""
Exercise signed view publication boundaries with local Git and a synthetic GitHub CLI.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("mode", ["success", "large", "stale", "race", "public", "unexpected"])
def test_publish_views_preserves_private_sources(tmp_path: Path, mode: str) -> None:
    """
    Restrict publication to reviewed images and schemas while fencing concurrent writers.

    Args:
        tmp_path (Path): Isolated synthetic repository and fake CLI directory.
        mode (str): Success, large image, changed head, public repository, or unrelated staged source scenario.

    Returns:
        None: Only permitted outputs reach one commit request, with explicit failures or skips elsewhere.
    """
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)

    for folder in ("docs/assets", "knowledge/schemas", "scripts/ci", "bin"):
        (root / folder).mkdir(parents=True)

    figure = b"<svg><desc>" + (b"x" * 131_072 if mode == "large" else b"synthetic figure") + b"</desc></svg>"
    (root / "docs/assets/plot.svg").write_bytes(figure)
    (root / "docs/assets/private.json").write_text('{"personal": "must stay local"}')
    (root / "knowledge/schemas/source.json").write_text("{}")
    (root / "docs/assets/knowledge-graph.json").write_text('{"nodes": []}')
    (root / "docs/assets/project-chapters").mkdir()
    (root / "docs/assets/project-chapters/checkpoints.json").write_text("{}")
    (root / "lessons.jsonl").write_text("private source")
    shutil.copyfile(_ROOT / "scripts/ci/publish-views.graphql", root / "scripts/ci/publish-views.graphql")
    shutil.copyfile(_ROOT / "scripts/ci/view_manifest.py", root / "scripts/ci/view_manifest.py")
    receipt = "docs/assets/view-provenance.json"
    subprocess.run(
        [
            sys.executable,
            str(root / "scripts/ci/view_manifest.py"),
            "--source",
            "lessons.jsonl",
            "--output",
            "docs/assets/plot.svg",
            "--receipt",
            receipt,
            "--revision",
            "f" * 40,
        ],
        cwd=root,
        check=True,
    )
    fake = root / "bin/gh"
    shutil.copyfile(_ROOT / "scripts/ci/tests/fixtures/publish-views-gh.sh", fake)
    fake.chmod(0o700)
    real_jq = shutil.which("jq")
    assert real_jq is not None

    # Model Linux's per-argument ceiling even when the regression runs on a different host.
    bounded_jq = root / "bin/jq"
    shutil.copyfile(_ROOT / "scripts/ci/tests/fixtures/publish_views_jq.py", bounded_jq)
    bounded_jq.chmod(0o700)

    if mode == "unexpected":
        subprocess.run(["git", "add", "lessons.jsonl"], cwd=root, check=True)

    capture = tmp_path / "captured.json"
    environment = {
        **os.environ,
        "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
        "GITHUB_REPOSITORY": "example/private",
        "GITHUB_SHA": "f" * 40,
        "RUNNER_TEMP": str(tmp_path),
        "QA_MODE": mode,
        "QA_REAL_JQ": real_jq,
        "QA_CAPTURE": str(capture),
        "QA_RACE": str(tmp_path / "raced"),
    }
    result = subprocess.run(
        ["bash", str(_ROOT / "scripts/ci/publish-views.sh"), "private"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == (1 if mode in {"public", "unexpected"} else 0), result.stderr

    if mode in {"success", "large", "race"}:
        payload = json.loads(capture.read_text())["variables"]["input"]
        assert payload["expectedHeadOid"] == "f" * 40
        additions = {item["path"]: item["contents"] for item in payload["fileChanges"]["additions"]}
        assert base64.b64decode(additions["docs/assets/plot.svg"], validate=True) == figure
        assert {item["path"] for item in payload["fileChanges"]["additions"]} == {
            "docs/assets/plot.svg",
            "knowledge/schemas/source.json",
            "docs/assets/knowledge-graph.json",
            "docs/assets/view-provenance.json",
        }
    else:
        assert not capture.exists()

    if mode in {"stale", "race"}:
        assert "::notice::" in result.stdout
        assert "/commit/" not in result.stdout

    assert not list(tmp_path.glob("identity-views.*"))
