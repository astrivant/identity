"""
Verify readable, complete map labels and fitted contours across deterministic render sizes.
"""

from __future__ import annotations

import math
from itertools import combinations

import pytest
from attrs import evolve
from matplotlib.patches import Circle, Ellipse
from matplotlib.transforms import Bbox
from witful.knowledge.applications import application_id
from witful.knowledge.emphasis import _gaussian_distance, _gaussian_profile, emphasis_layout
from witful.knowledge.map_labels import label_color, visible_segments
from witful.knowledge.models import Application, Discipline, Identity, Skill
from witful.knowledge.plotting import _map_plot


@pytest.mark.parametrize("count", [1, 12])
@pytest.mark.parametrize("dpi", [100, 130])
def test_labels_fit_their_bubbles_without_collisions(count: int, dpi: int) -> None:
    """
    Retain complete long names and clear, centered text at preview and publication resolution.

    Args:
        count (int): Number of equally weighted disciplines.
        dpi (int): Preview or exported raster resolution.

    Returns:
        None: All labels fit, stay opaque, and avoid each other at both output scales.
    """
    model = Identity(
        "root",
        "Example",
        tuple(
            Discipline(
                f"d{i}",
                f"Engineering discipline {i}",
                (Skill(f"s{i}a", "Reliable service operations"), Skill(f"s{i}b", "Schema verification")),
            )
            for i in range(count)
        ),
    )
    figure = _map_plot(model, ())
    figure.set_dpi(dpi)
    figure.draw_without_rendering()
    axis = figure.axes[0]
    labels = {text.get_gid(): text for text in axis.texts if (text.get_gid() or "").startswith("map-")}
    assert len(labels) == count * 3
    boxes = [text.get_window_extent() for text in axis.texts]
    assert not any(left.overlaps(right) for left, right in combinations(boxes, 2))

    for bubble in emphasis_layout(model, ()):
        discipline = next(item for item in model.disciplines if item.id == bubble.id)
        title = labels[f"map-discipline:{bubble.id}"]

        for key, name in [(f"map-discipline:{bubble.id}", discipline.name), *((f"map-skill:{s.id}", s.name) for s in discipline.skills)]:
            text = labels[key]
            assert " ".join(text.get_text().split()) == name
            assert text.get_horizontalalignment() == "center" and text.get_verticalalignment() == "center"
            assert text.get_alpha() == 1
            assert text.get_bbox_patch() is None
            bounds = text.get_window_extent().transformed(axis.transData.inverted())
            assert all(
                math.dist((x, y), (bubble.x, bubble.y)) < bubble.radius for x in (bounds.x0, bounds.x1) for y in (bounds.y0, bounds.y1)
            )

            if key.startswith("map-skill:"):
                assert text.get_window_extent().y1 < title.get_window_extent().y0
                assert title.get_zorder() > text.get_zorder()

        assert all(title.get_zorder() > artist.get_zorder() for artist in (*axis.patches, *axis.collections, *axis.lines))

    figure.clear()


def test_contours_follow_the_same_rotated_covariance_as_the_shadow() -> None:
    """
    Keep ellipse distance, line style, and drawing layers tied to the actual fitted distribution.

    Returns:
        None: Each contour has the requested Mahalanobis radius and stays behind the bubbles.
    """
    model = Identity("root", "Example", tuple(Discipline(f"d{i}", f"Area {i}") for i in range(6)))
    bubbles = emphasis_layout(model, ())
    profile = _gaussian_profile([(bubble.x, bubble.y) for bubble in bubbles], [bubble.score for bubble in bubbles])
    figure = _map_plot(model, ())
    axis = figure.axes[0]
    contours = [patch for patch in axis.patches if isinstance(patch, Ellipse) and not isinstance(patch, Circle)]
    assert len(contours) == 4

    for sigma, contour in zip((0.5, 1.0, 1.5, 2.0), contours, strict=True):
        angle = math.radians(contour.angle)
        point = (profile[0] + contour.width / 2 * math.cos(angle), profile[1] + contour.width / 2 * math.sin(angle))
        assert _gaussian_distance(point, profile) == pytest.approx(sigma)
        assert contour.center == pytest.approx(profile[:2])
        assert contour.get_linestyle() == ("-" if sigma.is_integer() else "--")
        assert axis.images[0].get_zorder() < contour.get_zorder() < 0
        assert contour.get_clip_path() is not None

    figure.clear()


def test_text_switches_to_dark_ink_as_the_fill_fades() -> None:
    """
    Favor legible contrast rather than fading lettering alongside its parent bubble.

    Returns:
        None: Dark opaque fills use white text; pale faded fills use dark ink.
    """
    assert label_color("#263748", 1.0, "#FFFFFF") == "white"
    assert label_color("#263748", 0.18, "#FFFFFF") == "#263748"


@pytest.mark.parametrize("reverse", [False, True])
def test_relationship_lines_leave_text_clear(reverse: bool) -> None:
    """
    Merge overlapping label exclusions and handle horizontal edges in both directions.

    Args:
        reverse (bool): Whether the source and target are reversed.

    Returns:
        None: No visible segment crosses either exclusion, and the remaining endpoints are preserved.
    """
    start, end = ((1.0, 0.0), (0.0, 0.0)) if reverse else ((0.0, 0.0), (1.0, 0.0))
    boxes = [Bbox.from_extents(0.2, -0.1, 0.5, 0.1), Bbox.from_extents(0.4, -0.1, 0.7, 0.1)]
    segments = visible_segments(start, end, boxes)
    assert len(segments) == 2
    assert segments[0][0] == start and segments[-1][1] == end
    assert sorted(abs(right[0] - left[0]) for left, right in segments) == pytest.approx([0.2, 0.3])


@pytest.mark.parametrize("dpi", [100, 130])
def test_font_sizes_depend_on_hierarchy_not_bubble_size_or_density(dpi: int) -> None:
    """
    Keep type consistent for unequal bubbles with different numbers and lengths of labels.

    Args:
        dpi (int): Preview or publication resolution.

    Returns:
        None: All discipline titles share one size, all skills another, without missing names or overlaps.
    """
    model = Identity(
        "root",
        "Example",
        tuple(
            Discipline(f"d{i}", f"Engineering area {i}", tuple(Skill(f"s{i}{j}", f"Service practice {j}") for j in range(count)))
            for i, count in enumerate((5, 3, 1))
        ),
    )
    event = Application("", "example", "d0", ("d0",), "verified", "Synthetic evidence", "2026-01-01T00:00:00Z")
    events = (evolve(event, id=application_id(event)),)
    assert len({bubble.radius for bubble in emphasis_layout(model, events)}) > 1
    figure = _map_plot(model, events)
    figure.set_dpi(dpi)
    figure.draw_without_rendering()
    labels = [text for text in figure.axes[0].texts if (text.get_gid() or "").startswith("map-")]
    titles = [text for text in labels if (text.get_gid() or "").startswith("map-discipline:")]
    skills = [text for text in labels if (text.get_gid() or "").startswith("map-skill:")]
    assert len(titles) == 3 and len(skills) == 9
    assert len({text.get_fontsize() for text in titles}) == len({text.get_fontsize() for text in skills}) == 1
    assert float(titles[0].get_fontsize()) > float(skills[0].get_fontsize())
    assert {" ".join(text.get_text().split()) for text in labels} == {
        name for discipline in model.disciplines for name in (discipline.name, *(skill.name for skill in discipline.skills))
    }
    boxes = [text.get_window_extent() for text in labels]
    assert not any(left.overlaps(right) for left, right in combinations(boxes, 2))
    figure.clear()
