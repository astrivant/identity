"""
Render measured scheduling history with the project's cached palette and typography.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import matplotlib as mpl
from matplotlib import font_manager
from matplotlib.figure import Figure

from test_matrix.models import Sample, load

if TYPE_CHECKING:
    from pathlib import Path


def render(paths: list[Path], destination: Path, repository: str, scope: str) -> None:
    """
    Plot comparable accepted runs, retaining explicit cold-start and missing-history states.

    Args:
        paths (list[Path]): Durable per-run aggregate files plus the current validated run.
        destination (Path): Explicit SVG output destination.
        repository (str): Owner namespace, preventing accidental fork-history reuse.
        scope (str): Compatible environment digest; other scopes are excluded visibly.

    Returns:
        None: Deterministic transparent figure with no fabricated timing samples.
    """
    from pathlib import Path

    samples = [load(path, Sample) for path in paths]
    compatible = {sample.run: sample for sample in samples if sample.repository == repository and sample.scope == scope}
    ordered = sorted(compatible.values(), key=lambda item: tuple(int(part) for part in item.run.split("-")))[-40:]
    palette = json.loads(Path("docs/assets/brand/pr-palette.json").read_text())
    font = Path("pkg/witful/life/resources/EBGaramond-Regular.otf")
    font_manager.fontManager.addfont(str(font))
    with mpl.rc_context(
        {
            "font.family": "EB Garamond",
            "svg.hashsalt": "witful-test-convergence",
            "text.color": palette["foreground"],
            "axes.labelcolor": palette["foreground"],
            "xtick.color": palette["foreground"],
            "ytick.color": palette["foreground"],
        }
    ):
        figure = Figure(figsize=(11, 3.2))
        axes = figure.subplots(1, 3)
        figure.suptitle("Test matrix convergence", fontsize=18, y=0.99)
        figure.text(0.5, 0.87, "Are duration predictions stabilizing as runner allocation changes?", ha="center", fontsize=12)
        x = list(range(1, len(ordered) + 1))
        values: list[tuple[list[float | None], str]] = [
            (
                [
                    None if row.prediction_error_seconds is None else row.prediction_error_seconds / max(1, row.predicted_tests)
                    for row in ordered
                ],
                "Mean absolute prediction error (s)",
            ),
            ([row.wall_seconds for row in ordered], "Elapsed test stage (s)"),
            ([row.shards for row in ordered], "Allocated runners"),
        ]
        for index, (axis, (ys, label)) in enumerate(zip(axes, values, strict=True)):
            axis.plot(x, ys, color=palette["series"][index], marker="o", linewidth=1.6, markersize=3)
            axis.set_ylabel(label)
            axis.set_xlabel("Accepted compatible main runs")
            axis.set_ylim(bottom=0)
            axis.spines[["top", "right"]].set_visible(False)
            axis.grid(axis="y", alpha=0.15)
            if not ordered:
                axis.set_xticks([])
                axis.set_yticks([])
            if not ordered or all(value is None for value in ys):
                axis.text(
                    0.5,
                    0.5,
                    "Awaiting measured main history" if not ordered else "Cold start",
                    ha="center",
                    transform=axis.transAxes,
                    fontsize=10,
                )
        figure.text(
            0.5,
            0.015,
            "CI-generated. Elapsed time spans planner start through fan-in; incompatible environments are separate histories.",
            ha="center",
            fontsize=9,
        )
        figure.subplots_adjust(left=0.07, right=0.98, bottom=0.22, top=0.77, wspace=0.42)
        destination.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(destination, transparent=True, metadata={"Date": None})

        # Matplotlib's path wrapping leaves trailing spaces; normalize text before hashing and Git review.
        if destination.suffix.lower() == ".svg":
            destination.write_text("\n".join(line.rstrip() for line in destination.read_text().splitlines()) + "\n")
