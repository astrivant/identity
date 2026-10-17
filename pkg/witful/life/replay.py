"""
Project causal journal prefixes and regenerate views from their saved knowledge inputs.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import matplotlib as mpl

from witful.files import replace_file
from witful.knowledge.contracts import as_data
from witful.knowledge.plotting import save_figure, write_plots
from witful.knowledge.rendering import graph_data
from witful.life.contracts import canonical, current_decisions, snapshot_identity, validate_archive
from witful.life.journal import renderer_fingerprint
from witful.life.models import Archive
from witful.life.path_plot import figure
from witful.life.paths import select

if TYPE_CHECKING:
    from pathlib import Path

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
        "paths": as_data(select(archive)),
    }
    destination = output / "life.json"
    replace_file(destination, canonical(report) + b"\n", expected=destination.read_bytes() if destination.exists() else None)
    paths = [destination]

    with mpl.rc_context(mpl.rcParamsDefault):
        # Embed glyph paths so hosted SVGs retain the bundled font without viewer installation.
        mpl.rcParams.update(
            {"font.family": "DejaVu Sans", "svg.fonttype": "path", "svg.hashsalt": hashlib.sha256(canonical(report)).hexdigest()}
        )
        paths.extend(save_figure(figure(archive), output, "life"))

    if historical and latest is not None:
        identity = snapshot_identity(latest)
        graph = output / "knowledge-graph.json"
        content = (json.dumps(graph_data(identity, latest.applications), indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
        replace_file(graph, content, expected=graph.read_bytes() if graph.exists() else None)
        paths.extend([graph, *write_plots(identity, latest.applications, output)])

    return paths
