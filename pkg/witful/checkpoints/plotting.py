"""
Render recent project visits and cumulative comparisons without implying proficiency scores.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import matplotlib as mpl
from matplotlib.figure import Figure

from witful.checkpoints.diff import compare, visits
from witful.checkpoints.snapshot import digest
from witful.files import replace_file
from witful.knowledge.contracts import as_data
from witful.knowledge.plotting import save_figure

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from witful.checkpoints.models import Checkpoint

__all__ = ["build"]


def _figure(pairs: Sequence[tuple[Checkpoint, Checkpoint]], title: str, question: str) -> Figure:
    """
    Show sparse signed additions, withdrawals, and revisions for each changed skill.

    Args:
        pairs (Sequence[tuple[Checkpoint, Checkpoint]]): Baseline/target pairs in newest-first display order.
        title (str): Short plot title.
        question (str): Question answered by this view.

    Returns:
        Figure: Annotated matrix with zero-change cells muted and no inferred initial growth.
    """
    differences = [compare(before, after) for before, after in pairs]
    names = {item.id: item.name for group in reversed(differences) for item in group}
    keys = sorted(names, key=lambda key: (names[key].casefold(), key))
    figure = Figure(figsize=(max(10, min(30, 5 + 2 * len(pairs))), max(4.5, 2.7 + len(keys) * 0.65)), layout="constrained")
    figure.suptitle(title + "\n" + question, fontsize=16)
    axis = figure.subplots()

    if not keys or not pairs:
        message = (
            "No changed skill evidence between these boundaries" if pairs else "Record a second project visit to compare with the baseline"
        )
        axis.text(0.5, 0.5, message, transform=axis.transAxes, ha="center", va="center", color="#586774")
        axis.set_axis_off()
        return figure

    # Cell brightness describes change volume; text retains direction and revisions separately.
    cells = [[0 for _ in pairs] for _ in keys]
    annotations: dict[tuple[int, int], str] = {}

    for column, group in enumerate(differences):
        for item in group:
            row = keys.index(item.id)
            learning, use = item.lessons, item.uses
            size = sum(len(values) for change in (learning, use) for values in (change.added, change.removed, change.revised))
            cells[row][column] = max(size, int(item.status != "retained"))
            annotations[row, column] = (
                f"L +{len(learning.added)} / -{len(learning.removed)} / ~{len(learning.revised)}\n"
                f"U +{len(use.added)} / -{len(use.removed)} / ~{len(use.revised)}"
                + (f"\n{item.status}" if item.status != "retained" else "")
            )

    maximum = max(max(row) for row in cells)
    axis.imshow(cells, cmap="Blues", vmin=0, vmax=max(2, maximum * 2), aspect="auto")
    axis.set_yticks(range(len(keys)), [names[key] for key in keys], fontsize=10)
    axis.set_xticks(
        range(len(pairs)),
        [f"{after.project} @ {after.revision[:7]}\nvs {before.project} @ {before.revision[:7]}" for before, after in pairs],
        fontsize=9,
        rotation=20,
        ha="right",
    )
    axis.tick_params(length=0)

    for (row, column), text in annotations.items():
        axis.text(column, row, text, ha="center", va="center", fontsize=9, color="#193448")

    axis.set_xlabel("L = documented lessons; U = observed uses; + added / - removed / ~ revised. Counts are not mastery.", labelpad=14)
    return figure


def build(events: Sequence[Checkpoint], destination: Path, limit: int = 8) -> tuple[Path, ...]:
    """
    Export full comparisons and bounded plots ordered by recorded project visits.

    Args:
        events (Sequence[Checkpoint]): Validated complete checkpoint history.
        destination (Path): Generated artifact directory.
        limit (int): Maximum recent comparisons shown in each plot, from one through twenty.

    Returns:
        tuple[Path, ...]: Complete JSON export and two SVG/PNG views.

    Raises:
        ValueError: The plot limit is outside the documented range.
    """
    if not 1 <= limit <= 20:
        raise ValueError("Checkpoint plot limit must be between one and twenty")

    endpoints = visits(events)
    adjacent = list(reversed(list(zip(endpoints[:-1], endpoints[1:], strict=True))))
    latest = [(before, endpoints[-1]) for before in reversed(endpoints[:-1])] if endpoints else []
    commits = list(zip(events[:-1], events[1:], strict=True))
    destination.mkdir(parents=True, exist_ok=True)
    payload = {
        "checkpoints": [as_data(event) for event in events],
        "commit_diffs": [
            {"before": before.id, "after": after.id, "skills": [as_data(item) for item in compare(before, after)]}
            for before, after in commits
        ],
        "visit_endpoints": [event.id for event in endpoints],
        "latest_vs_previous_visits": [
            {"before": before.id, "after": after.id, "skills": [as_data(item) for item in compare(before, after)]}
            for before, after in latest
        ],
    }
    path = destination / "checkpoints.json"
    replace_file(
        path, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(), expected=path.read_bytes() if path.exists() else None
    )
    outputs = [path]

    with mpl.rc_context(mpl.rcParamsDefault):
        mpl.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none", "svg.hashsalt": digest(payload)})

        for name, pairs, title, question in (
            ("checkpoint-transitions", adjacent, "Project chapters", "What changed between consecutive project visits?"),
            (
                "checkpoint-comparisons",
                latest,
                "Current chapter in context",
                "How does the latest recorded state differ from earlier project visits?",
            ),
        ):
            figure = _figure(pairs[:limit], title, question)
            outputs.extend(save_figure(figure, destination, name))

    return tuple(outputs)
