"""
Verify statistical axis geometry and unclipped labels independently of collection contents.
"""

from __future__ import annotations

import math
from itertools import combinations

import numpy as np
import pytest
from witful.knowledge.emphasis import _gaussian_distance, _gaussian_profile, emphasis_layout
from witful.knowledge.map_axes import principal_axes
from witful.knowledge.models import Discipline, Identity, Skill
from witful.knowledge.plotting import _map_plot


@pytest.mark.parametrize("angle", [0.0, math.pi / 4, -math.pi / 3])
def test_tips_follow_principal_variances_and_rotation(angle: float) -> None:
    """
    Check true standardized distances and orthogonal directions on translated, anisotropic fits.

    Args:
        angle (float): Known rotation of the larger-variance direction.

    Returns:
        None: Four tips are at 2.7 standardized deviations and labels stay outside the packing circle.
    """
    profile = (0.13, -0.09, 0.16, 0.04, math.cos(angle), math.sin(angle))
    guides = principal_axes(profile)
    assert [guide.name for guide in guides] == ["Major", "Minor"]
    vectors = []

    for guide, deviation in zip(guides, (0.4, 0.2), strict=True):
        assert math.dist(guide.start, guide.end) == pytest.approx(2 * 2.7 * deviation)
        assert tuple((start + end) / 2 for start, end in zip(guide.start, guide.end, strict=True)) == pytest.approx(profile[:2])
        vectors.append((guide.end[0] - profile[0], guide.end[1] - profile[1]))

        for tip, label in ((guide.start, guide.label_start), (guide.end, guide.label_end)):
            assert _gaussian_distance(tip, profile) == pytest.approx(2.7)
            assert math.hypot(*label) > 1.05
            assert math.dist(profile[:2], label) > math.dist(profile[:2], tip)

    assert sum(x * y for x, y in zip(*vectors, strict=True)) == pytest.approx(0)
    assert math.atan2(vectors[0][1], vectors[0][0]) == pytest.approx(angle)


@pytest.mark.parametrize("count", [0, 1, 6, 12])
def test_rendered_outer_ticks_leave_the_data_clear(count: int) -> None:
    """
    Exercise empty, regularized, and populated maps without clipping or label collisions.

    Args:
        count (int): Number of equally weighted disciplines in the test collection.

    Returns:
        None: Meaningful fits retain four short exterior ticks without crossing data or crowding labels.
    """
    model = Identity("root", "Example", tuple(Discipline(f"d{i}", f"Area {i}", (Skill(f"s{i}", "Contracts"),)) for i in range(count)))
    figure = _map_plot(model, ())
    figure.set_dpi(130)
    figure.draw_without_rendering()
    axis = figure.axes[0]
    labels = [text for text in axis.texts if (text.get_gid() or "").startswith("gaussian-axis-label:")]
    tips = [artist for artist in axis.collections if (artist.get_gid() or "").startswith("gaussian-axis-tip:")]
    ticks = [line for line in axis.lines if (line.get_gid() or "").startswith("gaussian-axis-tick:")]
    assert len(labels) == len(ticks) == (4 if count > 1 else 0)
    assert not tips
    assert not any((line.get_gid() or "").startswith("gaussian-axis-guide:") for line in axis.lines)

    if count > 1:
        bubbles = emphasis_layout(model, ())
        profile = _gaussian_profile([(bubble.x, bubble.y) for bubble in bubbles], [bubble.score for bubble in bubbles])
        assert {text.get_text() for text in labels} == {"Major axis", "Minor axis"}

        for tick in ticks:
            coordinates = np.asarray(tick.get_xydata(), dtype=np.float64)
            start, end = coordinates[0], coordinates[-1]
            assert np.linalg.norm(end - start) <= 0.070001

            # The whole visible segment stays outside the data envelope, including peripheral circles.
            for point in np.linspace(start, end, 9):
                x, y = float(point[0]), float(point[1])
                assert _gaussian_distance((x, y), profile) >= 2.7 - 1e-8
                assert math.hypot(x, y) >= 1.05 - 1e-8
                assert all(math.dist((x, y), (bubble.x, bubble.y)) >= bubble.radius + 0.049 for bubble in bubbles)
                assert axis.get_xlim()[0] < x < axis.get_xlim()[1]
                assert axis.get_ylim()[0] < y < axis.get_ylim()[1]
                assert not any(text.get_window_extent().padded(4).contains(*axis.transData.transform((x, y))) for text in axis.texts)

        for label in labels:
            bounds = label.get_window_extent()
            assert figure.bbox.contains(bounds.x0, bounds.y0) and figure.bbox.contains(bounds.x1, bounds.y1)
            assert label.get_alpha() == 1.0
            assert label.get_bbox_patch() is None

        # New exterior labels must stay clear of all existing titles and skill names, not just one another.
        boxes = [text.get_window_extent() for text in axis.texts]
        assert not any(left.overlaps(right) for left, right in combinations(boxes, 2))

    figure.clear()
