"""
Plot ordinal decision reassessments and observed context changes without causal claims.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

import matplotlib as mpl
from matplotlib.figure import Figure

from witful.knowledge.plotting import save_figure

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from witful.reflection.models import Assessment

FIGURES = {"decision-outcomes": "Past decisions, current knowledge", "decision-context": "What changed afterward"}
__all__ = ["FIGURES", "build"]


def build(assessments: Sequence[Assessment], destination: Path, *, synthetic: bool = False) -> tuple[Path, ...]:
    """
    Render both review views, including explicit empty and unknown-outcome states.

    Args:
        assessments (Sequence[Assessment]): Latest reviewed assessment per original decision.
        destination (Path): Output directory; public callers must supply synthetic data only.
        synthetic (bool): Mark demonstration plots explicitly rather than presenting them as real observations.

    Returns:
        tuple[Path, ...]: Deterministic SVG and PNG files for both views.
    """
    destination.mkdir(parents=True, exist_ok=True)
    outputs = []
    with mpl.rc_context(mpl.rcParamsDefault):
        mpl.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none", "svg.hashsalt": "witful-reflection-v1"})
        for name, title in FIGURES.items():
            context = name == "decision-context"
            pairs = [
                (item.observed_outcome, item.context_effect) if context else (item.current_support, item.observed_outcome)
                for item in assessments
            ]
            cells = Counter((x, y) for x, y in pairs if x is not None and y is not None)
            missing = len(assessments) - sum(cells.values())
            question = (
                "Did circumstances improve or worsen after the recorded outcome?"
                if context
                else "Which past choices still hold up, and how did they turn out?"
            )
            figure = Figure(figsize=(9, 6), layout="constrained")
            figure.suptitle(title + "\n" + question, fontsize=14, gid="plot-heading")
            axis = figure.subplots()
            axis.set(xlim=(-2.5, 2.5), ylim=(-2.5, 2.5), xticks=range(-2, 3), yticks=range(-2, 3))
            axis.set_xlabel("Observed outcome" if context else "Current support for the original choice")
            axis.set_ylabel("Observed change in circumstances" if context else "Observed outcome")
            axis.axhline(0, color="#b9c0c4", linewidth=0.7)
            axis.axvline(0, color="#b9c0c4", linewidth=0.7)
            axis.spines[["top", "right"]].set_visible(False)
            axis.grid(alpha=0.12)

            # Aggregate exact equal ratings rather than jittering ordinal values or overlapping labels.
            for (x, y), count in sorted(cells.items()):
                axis.scatter(x, y, s=180 + 80 * count, color="#407D61" if y > 0 else "#A36636" if y < 0 else "#697783", alpha=0.8)
                axis.text(x, y, str(count), ha="center", va="center", color="white", fontsize=11)
            if not cells:
                axis.text(0.5, 0.62, "No scored observations yet", transform=axis.transAxes, ha="center", color="#586774")
            prefix = "Synthetic example. " if synthetic else "Reviewed observations. "
            figure.supxlabel(
                prefix + f"Numbers count decisions; {missing} unknown/unscored.\n"
                "Ordinal ratings: -2 strongly negative, 0 neutral, +2 strongly positive. Association is not causation.",
                fontsize=9,
            )
            outputs.extend(save_figure(figure, destination, name))
    return tuple(outputs)
