"""
Verify historical replay uses saved sources and distinguishes toolchain drift from source changes.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from sapience.knowledge.plotting import write_plots
from sapience.knowledge.rendering import graph_data
from sapience.life.contracts import snapshot_identity
from sapience.life.journal import read_archive, record_decision
from sapience.life.models import Archive
from sapience.life.replay import render

if TYPE_CHECKING:
    from pathlib import Path

    from sapience.life.models import Decision


def test_replay_survives_current_source_edits_and_reproduces_bytes(source: Path, decision: Decision) -> None:
    """
    Reconstruct the old graph and figures after current journal and catalog contents are replaced.

    Args:
        source (Path): Synthetic source checkout.
        decision (Decision): Choice capturing its initial state.

    Returns:
        None: Saved inputs produce byte-identical figures and rerenders preserve modification times.
    """
    record_decision(source, decision)
    archive = read_archive(source)
    snapshot = archive.snapshots[0]
    identity = snapshot_identity(snapshot)
    expected = write_plots(identity, snapshot.applications, source / "before")
    (source / "lessons.jsonl").write_text("")
    (source / "knowledge/catalog.json").write_text("{}")
    (source / "knowledge/applications.jsonl").write_text("invalid")
    destination = source / "replayed"
    outputs = render(read_archive(source), source, destination, historical=True)
    assert json.loads((destination / "knowledge-graph.json").read_text()) == graph_data(identity, snapshot.applications)
    assert all(path.read_bytes() == (destination / path.name).read_bytes() for path in expected)
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in outputs}
    render(archive, source, destination, historical=True)
    assert before == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in outputs}


def test_replay_detects_renderer_drift_before_writing(source: Path, decision: Decision) -> None:
    """
    Require explicit acknowledgement when the current lock no longer matches the saved renderer.

    Args:
        source (Path): Synthetic checkout.
        decision (Decision): Choice with the original toolchain fingerprint.

    Returns:
        None: Strict replay leaves no output; acknowledged drift appears in the report.
    """
    record_decision(source, decision)
    archive = read_archive(source)
    (source / "poetry.lock").write_text("changed toolchain")
    output = source / "drift"

    with pytest.raises(ValueError, match="renderer differs"):
        render(archive, source, output, historical=True)

    assert not output.exists()
    render(archive, source, output, historical=True, allow_drift=True)
    assert json.loads((output / "life.json").read_text())["renderer_matches"] is False


def test_empty_life_has_no_invented_history(source: Path) -> None:
    """
    Render the base case without manufacturing decisions, snapshots, or usage observations.

    Args:
        source (Path): Toolchain fingerprint source.

    Returns:
        None: The empty report is explicit and creates only the life overview artifacts.
    """
    output = source / "empty"
    paths = render(Archive(), source, output, historical=True)
    assert len(paths) == 3
    assert json.loads((output / "life.json").read_text())["current"] == []
