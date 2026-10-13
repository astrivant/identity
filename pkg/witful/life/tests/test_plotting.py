"""
Verify public decision figures respect revisions, retirement, and deterministic rendering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from attrs import evolve
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from numpy.testing import assert_array_equal
from witful.life.journal import read_archive, record_decision
from witful.life.models import Archive
from witful.life.plotting import draw_changes, draw_influences, write_influences

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


def test_choice_rates_include_revision_retirement_and_reinstatement(source: Path, decision: Decision) -> None:
    """
    Distinguish accepted-state transitions from the number of observations recorded.

    Args:
        source (Path): Synthetic collection with snapshot inputs.
        decision (Decision): Initial accepted choice.

    Returns:
        None: Raw totals and per-entry differences preserve revision and retirement semantics.
    """
    initial = record_decision(source, decision)
    revised = record_decision(source, evolve(decision, supersedes=initial.id, choice="Review the storage contract"))
    retired = record_decision(source, evolve(decision, supersedes=revised.id, status="retired"))
    retirement_revision = record_decision(
        source, evolve(decision, supersedes=retired.id, status="retired", choice="Keep withdrawn with new evidence")
    )
    record_decision(source, evolve(decision, supersedes=retirement_revision.id))
    record_decision(source, evolve(decision, key="storage:second"))
    axis = Figure().subplots()
    draw_changes(axis, read_archive(source))
    lines = {line.get_label(): line for line in axis.lines}
    assert_array_equal(lines["Accepted choices"].get_ydata(), [1, 0, -1, 0, 1, 1])
    assert_array_equal(lines["Observations (+1 per entry)"].get_ydata(), [1] * 6)
    assert_array_equal(lines["Accepted choices"].get_xdata(), list(range(1, 7)))
    assert "6 observations | 2 accepted choices" in [text.get_text() for text in axis.texts]
    assert axis.get_ylabel() == "Net change per entry"


def test_equal_choice_rates_keep_both_series_distinguishable(source: Path, decision: Decision) -> None:
    """
    Keep two coincident rates visible without shifting or inventing observations.

    Args:
        source (Path): Synthetic collection.
        decision (Decision): Its only accepted choice.

    Returns:
        None: Identical values retain separate styles, legend entries, and a visible single-point marker.
    """
    record_decision(source, decision)
    axis = Figure().subplots()
    draw_changes(axis, read_archive(source))
    lines = {line.get_label(): line for line in axis.lines}
    accepted = lines["Accepted choices"]
    observations = lines["Observations (+1 per entry)"]
    assert_array_equal(accepted.get_ydata(), [1])
    assert_array_equal(observations.get_ydata(), [1])
    assert accepted.get_linestyle() != observations.get_linestyle()
    assert accepted.get_linewidth() > observations.get_linewidth()
    assert observations.get_zorder() > accepted.get_zorder()
    assert accepted.get_marker() == "o"
    assert axis.get_legend_handles_labels()[1] == ["Accepted choices", "Observations (+1 per entry)"]


def test_empty_choice_rate_has_no_synthetic_observation() -> None:
    """
    Retain a truthful empty view before any journal entry exists.

    Returns:
        None: No accepted-choice or observation series is fabricated at position zero.
    """
    axis = Figure().subplots()
    draw_changes(axis, Archive())
    assert axis.get_legend_handles_labels() == ([], [])
    assert "No choices recorded" in [text.get_text() for text in axis.texts]
    assert "0 observations | 0 accepted choices" in [text.get_text() for text in axis.texts]
