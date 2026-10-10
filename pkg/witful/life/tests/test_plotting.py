"""
Verify public decision figures respect revisions, retirement, and deterministic rendering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from attrs import evolve
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from witful.life.journal import read_archive, record_decision
from witful.life.plotting import draw_influences, write_influences

if TYPE_CHECKING:
    from pathlib import Path

    from witful.life.models import Decision


def test_revised_and_retired_decisions_do_not_inflate_influences(source: Path, decision: Decision) -> None:
    """
    Render current accepted references after one revision and another decision's retirement.

    Args:
        source (Path): Synthetic collection with validated snapshot inputs.
        decision (Decision): Initial decision referring to one insight.

    Returns:
        None: Only the latest accepted reference remains and repeated exports match byte for byte.
    """
    first = record_decision(source, decision)
    record_decision(source, evolve(decision, supersedes=first.id, concept_ids=("s",)))
    other = record_decision(source, evolve(decision, key="storage:other"))
    record_decision(source, evolve(decision, key="storage:other", supersedes=other.id, status="retired"))
    archive = read_archive(source)
    axis = Figure().subplots()
    draw_influences(axis, archive)
    assert [label.get_text() for label in axis.get_yticklabels()] == ["Schemas"]
    assert len(axis.patches) == 1
    assert isinstance(axis.patches[0], Rectangle)
    assert axis.patches[0].get_width() == 1
    outputs = write_influences(archive, source / "figures")
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in outputs}
    write_influences(archive, source / "figures")
    assert before == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in outputs}
    assert "What informs my decisions" in (source / "figures/decision-influences.svg").read_text()
