"""
Verify that the public examples remain complete, independent and reproducible.
"""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from documentation.knowledge.examples import examples
from documentation.knowledge.overview import overview
from witful.knowledge.applications import validate_applications
from witful.knowledge.compiler import index
from witful.knowledge.contracts import as_data, structure
from witful.knowledge.metrics import graph_edges
from witful.knowledge.models import Application, Discipline, Identity, Insight, Lesson, Skill

if TYPE_CHECKING:
    from matplotlib.text import Text


def test_examples_keep_all_levels_and_evidence_inside_their_own_identity() -> None:
    """
    Reject cross-collection evidence even when the example skill names match.

    Returns:
        None: Every level is populated, IDs are disjoint and no relation or observation crosses an identity boundary.
    """
    collections = examples()
    assert len(collections) == 3
    assert examples() == collections
    identifiers: list[set[str]] = []

    for example in collections:
        nodes, _ = index(example.identity)
        assert {type(node) for node in nodes.values()} == {Identity, Discipline, Skill, Lesson, Insight}
        identifiers.append(set(nodes))
        validate_applications(example.identity, example.applications)
        edges = graph_edges(example.identity, example.applications)
        assert {edge.kind for edge in edges} == {"contains", "related", "requires", "transfers", "co-use", "observed-transfer"}
        assert all(edge.source in nodes and edge.target in nodes for edge in edges)
        assert all(event.outcome == "unassessed" for event in example.applications)

    for left, right in combinations(identifiers, 2):
        assert left.isdisjoint(right)

    with pytest.raises(ValueError, match="Unknown application discipline"):
        validate_applications(collections[0].identity, collections[1].applications)


def test_committed_graph_data_replays_current_examples() -> None:
    """
    Bind the public downloadable graph to the generator's current synthetic inputs.

    Returns:
        None: Committed data validates against runtime schemas and preserves the current complete typed graph.
    """
    source = Path(__file__).resolve().parents[2] / "docs/assets/knowledge-collections-example.json"
    payload = json.loads(source.read_text())
    assert payload["synthetic"] is True

    for collection, example in zip(payload["collections"], examples(), strict=True):
        assert structure(collection["identity"], Identity) == example.identity
        assert tuple(structure(event, Application) for event in collection["applications"]) == example.applications
        assert collection["edges"] == [as_data(edge) for edge in graph_edges(example.identity, example.applications)]


def test_overview_displays_every_concept_with_legible_separate_labels() -> None:
    """
    Check actual rendered bounds, so complete source data cannot hide clipped or overlapping labels.

    Returns:
        None: Every concept has a drawn node, labels stay inside its panel, and labels do not overlap.
    """
    collections = examples()
    figure = overview(collections)
    figure.draw_without_rendering()

    for example, axis in zip(collections, figure.axes, strict=True):
        nodes, _ = index(example.identity)
        rendered = {patch.get_gid() for patch in axis.patches if patch.get_gid()}
        assert rendered == {f"concept:{identifier}" for identifier in nodes}
        texts: list[Text] = list(axis.texts)
        bounds = [text.get_window_extent() for text in texts]
        panel = axis.get_window_extent()
        assert all(panel.contains(box.x0, box.y0) and panel.contains(box.x1, box.y1) for box in bounds)
        assert all(not left.overlaps(right) for left, right in combinations(bounds, 2))

    figure.clear()
