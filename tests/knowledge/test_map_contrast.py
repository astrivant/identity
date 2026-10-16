"""
Keep sparse knowledge-map connections visible without manufacturing verified evidence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from xml.etree import ElementTree

import pytest
from attrs import evolve
from matplotlib.colors import to_rgb
from matplotlib.patches import Circle
from witful.knowledge.applications import application_id
from witful.knowledge.models import Application, Discipline, Identity, Relation, Skill
from witful.knowledge.plotting import _map_plot, save_figure

if TYPE_CHECKING:
    from pathlib import Path


def _example(outcome: Literal["unassessed", "verified"]) -> tuple[Identity, tuple[Application, ...]]:
    """
    Pair recent and old observations so peripheral fading is exercised too.

    Args:
        outcome (Literal["unassessed", "verified"]): Explicit synthetic evidence rating.

    Returns:
        tuple[Identity, tuple[Application, ...]]: Small collection with containment, curated and observed edges.
    """
    identity = Identity(
        "example",
        "Synthetic contrast check",
        tuple(Discipline(f"d{i}", f"Practice {i}", (Skill(f"s{i}", f"Capability {i}"),)) for i in range(3)),
        (Relation("s0", "s2", "related", "Synthetic curated relationship."),),
    )
    events = tuple(
        Application("", f"task{i}", f"d{i}", (f"s{i}", f"s{i + 1}"), outcome, "Synthetic contrast fixture.", date)
        for i, date in enumerate(("2026-01-30T12:00:00+00:00", "2025-01-01T12:00:00+00:00"))
    )
    return identity, tuple(evolve(event, id=application_id(event)) for event in events)


@pytest.mark.parametrize("outcome", ["unassessed", "verified"])
def test_relationships_remain_visible_when_evidence_is_sparse(outcome: Literal["unassessed", "verified"]) -> None:
    """
    Require readable links above fills while keeping evidence colors and line semantics separate.

    Args:
        outcome (Literal["unassessed", "verified"]): Whether the synthetic observations report supporting evidence.

    Returns:
        None: Peripheral and zero-strength edges remain visible without granting them verified styling.
    """
    figure = _map_plot(*_example(outcome))
    axis = figure.axes[0]
    links = [line for line in axis.lines if (line.get_gid() or "").startswith("map-edge:")]
    assert links
    assert len({line.get_gid() for line in links}) == len(links)
    assert any((patch.get_alpha() or 0) < 0.18 for patch in axis.patches if isinstance(patch, Circle))

    for line in links:
        kind = (line.get_gid() or "").split(":")[1]
        alpha = line.get_alpha()
        assert line.get_linewidth() >= 1.0
        assert alpha is not None and alpha >= 0.75
        assert line.get_zorder() > max(patch.get_zorder() for patch in axis.patches if isinstance(patch, Circle))
        assert line.get_linestyle() == ("--" if kind == "related" else "-")
        verified = outcome == "verified" and kind in {"co-use", "observed-transfer"}
        assert (to_rgb(line.get_color()) == to_rgb("#407D61")) == verified

        # A neutral link must contrast with the white canvas independently of
        # whether its input history can justify a verified/weighted stroke.
        if not verified:
            rgb = [alpha * channel + 1 - alpha for channel in to_rgb(line.get_color())]
            linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in rgb]
            luminance = sum(weight * channel for weight, channel in zip((0.2126, 0.7152, 0.0722), linear, strict=True))
            assert 1.05 / (luminance + 0.05) >= 3

    figure.clear()


def test_projection_keeps_the_same_connection_style(tmp_path: Path) -> None:
    """
    Ensure awareness-style cropping changes headings rather than relationship appearance.

    Args:
        tmp_path (Path): Isolated destinations for standalone and projected figures.

    Returns:
        None: Both exports retain identical link styles, with only the standalone outer headings present.
    """
    styles: list[list[str]] = []

    for projection in (False, True):
        destination = tmp_path / str(projection)
        save_figure(_map_plot(*_example("unassessed")), destination, "map", projection=projection)
        root = ElementTree.fromstring((destination / "map.svg").read_text())
        groups = [element for element in root.iter() if element.get("id", "").startswith("map-edge:")]
        styles.append([child.attrib["style"] for group in groups for child in group if "style" in child.attrib])
        assert any(element.get("id") == "plot-heading" for element in root.iter()) != projection

    assert styles[0] and styles[0] == styles[1]
