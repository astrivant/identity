"""
Render recorded lesson coverage without treating record counts as proficiency scores.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from io import BytesIO
from textwrap import fill
from typing import TYPE_CHECKING

import matplotlib as mpl
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from sapience.files import replace_file
from sapience.lessons import read_journal

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from sapience.lessons import Lesson


@dataclass(frozen=True)
class TopicCount:
    """
    Count each journal record once within its recorded topic.

    Attributes:
        topic (str): Display topic after explicit naming aliases; new concepts remain visible.
        active (int): Records that have not been superseded.
        superseded (int): Retained historical records replaced by later guidance.
    """

    topic: str
    active: int
    superseded: int


def topic_counts(records: Sequence[Lesson], *, aliases: Mapping[str, str] | None = None) -> list[TopicCount]:
    """
    Separate current guidance from history using explicit supersession links.

    Args:
        records (Sequence[Lesson]): Validated journal, with unique IDs and existing correction targets.
        aliases (Mapping[str, str] | None): Explicit display-only topic names, preserving original records.

    Returns:
        list[TopicCount]: Every topic, ordered by decreasing active count, historical count, then name.
    """
    names = aliases or {}
    replaced = {record.supersedes for record in records if record.supersedes is not None}
    active = Counter(names.get(record.topic, record.topic) for record in records if record.id not in replaced)
    historical = Counter(names.get(record.topic, record.topic) for record in records if record.id in replaced)
    counts = [TopicCount(topic, active[topic], historical[topic]) for topic in active.keys() | historical.keys()]
    return sorted(counts, key=lambda item: (-item.active, -item.superseded, item.topic.casefold(), item.topic))


def write_plot(journal: Path, destination: Path, *, aliases: Mapping[str, str] | None = None) -> list[Path]:
    """
    Generate a portable SVG and PNG from the reviewed journal alone.

    Args:
        journal (Path): Source JSONL; validated before any output changes.
        destination (Path): Directory receiving lesson-coverage.svg and lesson-coverage.png.
        aliases (Mapping[str, str] | None): Collection-owned display aliases, without changing the source journal.

    Returns:
        list[Path]: Artifact paths, preserving existing bytes and modification times when unchanged.

    Raises:
        ValueError: The journal fails validation.
        RuntimeError: A destination changes concurrently during replacement.
    """
    records = read_journal(journal)
    counts = topic_counts(records, aliases=aliases)
    active = sum(item.active for item in counts)
    historical = sum(item.superseded for item in counts)

    # Bind the plot to its exact validated inputs without a wall-clock timestamp or model-generated classification.
    payload = json.dumps([asdict(record) for record in records], sort_keys=True, ensure_ascii=False).encode()
    digest = hashlib.sha256(payload).hexdigest()
    latest = max((datetime.fromisoformat(record.observed_at).astimezone(UTC) for record in records), default=None)
    observed = latest.date().isoformat() if latest else "no observations"

    # Reset user matplotlibrc overrides; fixed fonts, vector IDs, and metadata make repeated renders stable in one toolchain.
    with mpl.rc_context(mpl.rcParamsDefault):
        mpl.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none", "svg.hashsalt": digest})
        height = max(4.5, 2.5 + len(counts) * 0.48)
        figure = Figure(figsize=(14, height), facecolor="#FFFFFF")
        axis = figure.add_axes((0.43, 0.105, 0.51, 0.77))
        figure.text(0.04, 0.963, "What you have taught me", fontsize=24, weight="bold", color="#243444", va="top")
        figure.text(
            0.04,
            0.923,
            f"{active} active lessons  |  {len(counts)} recorded topics  |  {historical} superseded",
            fontsize=12,
            color="#596775",
            va="top",
        )

        # Stacked history remains visible, but ranking and the primary color describe current recorded guidance only.
        positions = list(range(len(counts)))
        axis.barh(positions, [item.active for item in counts], height=0.56, color="#327B69", label="Active")
        axis.barh(
            positions,
            [item.superseded for item in counts],
            left=[item.active for item in counts],
            height=0.56,
            color="#CDD4DB",
            label="Superseded",
        )
        axis.set_yticks(positions, [fill(item.topic, width=43) for item in counts], fontsize=10.5, color="#293946")
        axis.invert_yaxis()
        maximum = max((item.active + item.superseded for item in counts), default=1)
        axis.set_xlim(0, max(1, maximum) * 1.16)
        axis.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=7))
        axis.set_xlabel("Recorded lessons", fontsize=11, color="#596775", labelpad=12)
        axis.set_axisbelow(True)
        axis.grid(axis="x", color="#E9EDF0", linewidth=0.8)
        axis.tick_params(axis="both", length=0, pad=10)
        axis.spines[["top", "right", "left", "bottom"]].set_visible(False)
        axis.legend(loc="lower right", bbox_to_anchor=(1, 1.01), ncol=2, frameon=False, fontsize=10)

        for index, item in enumerate(counts):
            label = f"{item.active}" + (f" + {item.superseded} prior" if item.superseded else "")
            axis.text(item.active + item.superseded + maximum * 0.015, index, label, va="center", fontsize=10, color="#293946")

        if not counts:
            axis.text(0.5, 0.5, "No lessons recorded yet", transform=axis.transAxes, ha="center", color="#596775")

        figure.text(
            0.04, 0.042, "Counts describe documented coverage, not mastery. Unrecorded topics are not shown.", fontsize=10, color="#596775"
        )
        figure.text(0.04, 0.022, f"Latest observation: {observed}  |  Validated journal SHA256: {digest[:16]}", fontsize=9, color="#7B8792")
        outputs: list[Path] = []

        # Keep both formats adjacent: SVG stays sharp in the README; PNG opens directly in image viewers.
        for extension in ("svg", "png"):
            buffer = BytesIO()
            metadata = (
                {"Date": None, "Creator": "identity lesson coverage"} if extension == "svg" else {"Software": "identity lesson coverage"}
            )
            figure.savefig(buffer, format=extension, dpi=140, metadata=metadata)
            content = buffer.getvalue()

            # Matplotlib pads multiline SVG paths; normalize insignificant line endings for clean generated diffs.
            if extension == "svg":
                content = b"\n".join(line.rstrip() for line in content.splitlines()) + b"\n"

            path = destination / f"lesson-coverage.{extension}"
            replace_file(path, content, expected=path.read_bytes() if path.exists() else None)
            outputs.append(path)

        figure.clear()
        return outputs
