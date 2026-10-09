"""
Project causal journal prefixes and regenerate views from their saved knowledge inputs.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from textwrap import fill
from typing import TYPE_CHECKING

import matplotlib as mpl
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from witful.files import replace_file
from witful.knowledge.compiler import index
from witful.knowledge.contracts import as_data
from witful.knowledge.plotting import save_figure, write_plots
from witful.knowledge.rendering import graph_data
from witful.life.contracts import canonical, current_decisions, snapshot_identity, validate_archive
from witful.life.journal import renderer_fingerprint
from witful.life.models import Archive

if TYPE_CHECKING:
    from pathlib import Path

    from witful.life.models import Event

__all__ = ["prefix", "render"]


def prefix(archive: Archive, through: str | None = None) -> Archive:
    """
    Select an inclusive causal prefix without sorting by timestamps or dropping retired decisions.

    Args:
        archive (Archive): Complete journal and snapshots.
        through (str | None): Exact last event ID, or None for the complete journal.

    Returns:
        Archive: Validated selected history with only its referenced snapshots.

    Raises:
        ValueError: The history is invalid or the requested event does not exist.
    """
    validate_archive(archive)
    events = archive.events

    if through is not None:
        identifiers = [event.id for event in events]

        if through not in identifiers:
            raise ValueError("Unknown replay event ID")

        events = events[: identifiers.index(through) + 1]

    selected = {event.snapshot_id for event in events}
    return Archive(events, tuple(item for item in archive.snapshots if item.id in selected))


def _figure(archive: Archive) -> Figure:
    """
    Separate recorded decisions and revisions from observed applications of teachings.

    Args:
        archive (Archive): Validated historical prefix.

    Returns:
        Figure: Decision timeline and direct concept references in currently accepted choices.
    """
    active: dict[str, Event] = {}
    accepted = [0]

    for event in archive.events:
        active[event.decision.key] = event
        accepted.append(sum(item.decision.status == "accepted" for item in active.values()))

    labels: dict[str, str] = {}

    for snapshot in archive.snapshots:
        labels.update({key: node.name for key, node in index(snapshot_identity(snapshot))[0].items()})

    counts = Counter(
        identifier for event in active.values() if event.decision.status == "accepted" for identifier in event.decision.concept_ids
    )
    selected = sorted(counts, key=lambda key: (-counts[key], key))[:15]
    figure = Figure(figsize=(14, 6), facecolor="white")
    left, right = figure.subplots(1, 2)
    figure.subplots_adjust(left=0.07, right=0.97, top=0.8, bottom=0.18, wspace=0.85)
    figure.suptitle("Life: recorded choices", x=0.04, ha="left", fontsize=22, color="#263748")
    sequence = list(range(len(archive.events) + 1))
    left.step(sequence, sequence, where="post", label="All observations", color="#A36636")
    left.step(sequence, accepted, where="post", label="Accepted choices", color="#407D61")
    left.set_xlabel("Journal position")
    left.set_ylabel("Count")
    left.legend(frameon=False)
    left.xaxis.set_major_locator(MaxNLocator(integer=True))
    left.yaxis.set_major_locator(MaxNLocator(integer=True))
    right.barh([fill(labels[key], 28) for key in selected], [counts[key] for key in selected], color="#366A87")
    right.invert_yaxis()
    right.set_title("Concepts linked to accepted choices", fontsize=11)
    right.xaxis.set_major_locator(MaxNLocator(integer=True))

    if not selected:
        right.text(0.5, 0.5, "No choices recorded", ha="center", transform=right.transAxes)

    for axis in (left, right):
        axis.spines[["top", "right"]].set_visible(False)

    figure.text(
        0.04, 0.05, "Revisions retain earlier choices. Links document rationale; they do not add application-use counts.", color="#697783"
    )
    return figure


def render(archive: Archive, root: Path, output: Path, *, historical: bool = False, allow_drift: bool = False) -> list[Path]:
    """
    Render decision state and optionally the exact saved knowledge inputs behind its last event.

    Args:
        archive (Archive): Complete history or selected inclusive prefix.
        root (Path): Current checkout used only to fingerprint the rendering toolchain.
        output (Path): Explicit destination, separate from authoritative source records.
        historical (bool): Also regenerate the saved snapshot's graph and knowledge plots.
        allow_drift (bool): Acknowledge renderer differences; the output still reports them.

    Returns:
        list[Path]: Derived JSON and image paths, preserving unchanged files.

    Raises:
        ValueError: Historical rendering detects unacknowledged code or environment drift.
    """
    validate_archive(archive)
    heads = current_decisions(archive)
    snapshots = {snapshot.id: snapshot for snapshot in archive.snapshots}
    latest = snapshots[archive.events[-1].snapshot_id] if archive.events else None
    fingerprint = renderer_fingerprint(root)
    matches = latest is None or latest.renderer == fingerprint

    # Fail before writing any artifact when historical byte reproducibility cannot be claimed.
    if historical and not matches and not allow_drift:
        raise ValueError("Replay renderer differs from the snapshot; restore its toolchain or explicitly use --allow-renderer-drift")

    report = {
        "head": archive.events[-1].id if archive.events else None,
        "snapshot": latest.id if latest else None,
        "events": [as_data(event) for event in archive.events],
        "current": [as_data(event) for event in heads],
        "renderer_matches": matches,
        "recorded_renderer": list(latest.renderer) if latest else [],
        "actual_renderer": list(fingerprint),
    }
    destination = output / "life.json"
    replace_file(destination, canonical(report) + b"\n", expected=destination.read_bytes() if destination.exists() else None)
    paths = [destination]

    with mpl.rc_context(mpl.rcParamsDefault):
        mpl.rcParams.update(
            {"font.family": "DejaVu Sans", "svg.fonttype": "none", "svg.hashsalt": hashlib.sha256(canonical(report)).hexdigest()}
        )
        paths.extend(save_figure(_figure(archive), output, "life"))

    if historical and latest is not None:
        identity = snapshot_identity(latest)
        graph = output / "knowledge-graph.json"
        content = (json.dumps(graph_data(identity, latest.applications), indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
        replace_file(graph, content, expected=graph.read_bytes() if graph.exists() else None)
        paths.extend([graph, *write_plots(identity, latest.applications, output)])

    return paths
