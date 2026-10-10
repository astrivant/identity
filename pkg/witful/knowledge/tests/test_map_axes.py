"""
Verify compact principal-axis spokes without disturbing the plotted data or its labels.
"""

from __future__ import annotations

import math
from itertools import combinations

import numpy as np
import pytest
from witful.knowledge import plotting
from witful.knowledge.emphasis import Bubble, _gaussian_distance, _gaussian_profile, emphasis_layout
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
        None: Unobstructed spoke starts are at 2.7 standardized deviations on the fitted axes.
    """
    profile = (0.13, -0.09, 0.16, 0.04, math.cos(angle), math.sin(angle))
    guides = principal_axes(profile)
    assert [guide.name for guide in guides] == ["Major", "Minor"]
    vectors = []

    for guide, deviation in zip(guides, (0.4, 0.2), strict=True):
        assert math.dist(guide.start, guide.end) == pytest.approx(2 * 2.7 * deviation)
        assert tuple((start + end) / 2 for start, end in zip(guide.start, guide.end, strict=True)) == pytest.approx(profile[:2])
        vectors.append((guide.end[0] - profile[0], guide.end[1] - profile[1]))

        for tip in (guide.start, guide.end):
            assert _gaussian_distance(tip, profile) == pytest.approx(2.7)

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
    assert not labels
    assert not any("2.7" in text.get_text() for text in axis.texts)
    assert len(ticks) == (4 if count > 1 else 0)
    assert not tips
    assert not any((line.get_gid() or "").startswith("gaussian-axis-guide:") for line in axis.lines)

    if count > 1:
        bubbles = emphasis_layout(model, ())
        profile = _gaussian_profile([(bubble.x, bubble.y) for bubble in bubbles], [bubble.score for bubble in bubbles])
        # Distance-only labels must not reserve a wide margin that shrinks the bubbles on a PDF page.
        threshold_tips = [tip for guide in principal_axes(profile) for tip in (guide.start, guide.end)]
        bound = max(1.15, max(abs(value) for tip in threshold_tips for value in tip) + 0.1)
        assert max(abs(value) for value in (*axis.get_xlim(), *axis.get_ylim())) <= bound + 1e-8

        for tick in ticks:
            coordinates = np.asarray(tick.get_xydata(), dtype=np.float64)
            start, end = coordinates[0], coordinates[-1]
            assert np.linalg.norm(end - start) <= 0.070001
            direction = (profile[4], profile[5]) if ":major:" in (tick.get_gid() or "") else (-profile[5], profile[4])

            # Each outer segment sits on the actual center-originating axis, not merely parallel to it.
            for endpoint in (start, end):
                dx, dy = endpoint - np.asarray(profile[:2])
                assert dx * direction[1] - dy * direction[0] == pytest.approx(0, abs=1e-8)
            assert np.linalg.norm(end - profile[:2]) > np.linalg.norm(start - profile[:2])

            # The whole visible segment stays outside the data envelope, including peripheral circles.
            for point in np.linspace(start, end, 9):
                x, y = float(point[0]), float(point[1])
                assert _gaussian_distance((x, y), profile) >= 2.7 - 1e-8
                assert all(math.dist((x, y), (bubble.x, bubble.y)) >= bubble.radius + 0.049 for bubble in bubbles)
                assert axis.get_xlim()[0] < x < axis.get_xlim()[1]
                assert axis.get_ylim()[0] < y < axis.get_ylim()[1]
                assert not any(text.get_window_extent().padded(4).contains(*axis.transData.transform((x, y))) for text in axis.texts)

        # The compact view retains readable titles and skills without any collisions.
        boxes = [text.get_window_extent() for text in axis.texts]
        assert not any(left.overlaps(right) for left, right in combinations(boxes, 2))

    figure.clear()


@pytest.mark.parametrize("angle", [0.0, math.pi / 4, -math.pi / 3])
def test_spokes_move_only_for_intersecting_bubbles(angle: float) -> None:
    """
    Leave unobstructed directions compact while moving one spoke beyond a nearby bubble.

    Args:
        angle (float): Rotation shared by the fitted axes and synthetic bubble.

    Returns:
        None: Only the obstructed spoke moves, with the same direction and a visible clearance.
    """
    cosine, sine = math.cos(angle), math.sin(angle)
    profile = (0.13, -0.09, 0.04, 0.01, cosine, sine)
    bubble = Bubble("obstacle", 1, profile[0] + 0.6 * cosine, profile[1] + 0.6 * sine, 0.1, 1)
    original = principal_axes(profile)
    adjusted = principal_axes(profile, (bubble,))
    assert adjusted[0].start == pytest.approx(original[0].start)
    assert adjusted[1] == original[1]
    assert adjusted[0].end == pytest.approx((profile[0] + 0.75 * cosine, profile[1] + 0.75 * sine))
    assert math.dist(adjusted[0].end, (bubble.x, bubble.y)) == pytest.approx(bubble.radius + 0.05)


@pytest.mark.parametrize("angle", [0.0, math.pi / 4, -math.pi / 3])
def test_mean_cross_and_outline_share_the_fitted_rotation(angle: float, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Check both rendered marker paths against known rotated principal directions.

    Args:
        angle (float): Principal-axis rotation in radians.
        monkeypatch (pytest.MonkeyPatch): Replace the fit with controlled geometry.

    Returns:
        None: Both strokes and their white outline align with the axes at the fitted mean.
    """
    profile = (0.13, -0.09, 0.16, 0.04, math.cos(angle), math.sin(angle))
    monkeypatch.setattr(plotting, "_gaussian_profile", lambda *_: profile)
    model = Identity("root", "Example", tuple(Discipline(f"d{i}", f"Area {i}", (Skill(f"s{i}", "Contracts"),)) for i in range(6)))
    figure = _map_plot(model, ())
    markers = [artist for artist in figure.axes[0].collections if (artist.get_gid() or "").startswith("gaussian-mean:")]
    assert {marker.get_gid() for marker in markers} == {"gaussian-mean:underlay", "gaussian-mean:foreground"}

    for marker in markers:
        assert tuple(np.asarray(marker.get_offsets(), dtype=np.float64)[0]) == pytest.approx(profile[:2])
        vertices = np.asarray(marker.get_paths()[0].vertices, dtype=np.float64)

        for (start, end), direction in zip(
            ((vertices[0], vertices[1]), (vertices[2], vertices[3])), ((profile[4], profile[5]), (-profile[5], profile[4])), strict=True
        ):
            vector = end - start
            assert vector / np.linalg.norm(vector) == pytest.approx(direction)

    figure.clear()
