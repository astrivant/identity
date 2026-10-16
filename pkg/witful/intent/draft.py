"""
Prepare unreviewed capability candidates from the canonical repertoire and exact CodeGraph manifest.
"""

from __future__ import annotations

from importlib.metadata import version
from typing import TYPE_CHECKING

from witful.intent.contracts import QUERY_VERSION, SCHEMA_VERSION, fingerprint
from witful.intent.models import Anchor, Assertion, Evidence, Input, Scope, State

if TYPE_CHECKING:
    from witful.codegraph.models import Graph
    from witful.intent.models import File
    from witful.repertoire.models import Inventory


def environment(graph: Graph, files: tuple[File, ...]) -> dict[str, str]:
    """
    Bind required source-side inputs to the authenticated graph rather than caller claims.

    Args:
        graph (Graph): Authenticated current CodeGraph.
        files (tuple[File, ...]): Exact clean source universe.

    Returns:
        dict[str, str]: Canonical input digests; the full manifest also covers unrecognized lockfile names.
    """
    return {
        "parser": fingerprint(graph.indexer),
        "documentation-parser": fingerprint(("docref/1", version("Pygments"))),
        "configuration": fingerprint(graph.enrollment),
        "dependency-locks": fingerprint(tuple(item for item in files if "lock" in item.path.rsplit("/", 1)[-1])),
    }


def prepare(graph: Graph, files: tuple[File, ...], inventory: Inventory, now: int) -> State:
    """
    Join existing tool IDs without inventing uses, semantic reads or verified intent.

    Args:
        graph (Graph): Current enrolled graph, whose topology is not a safety proof.
        files (tuple[File, ...]): Independently captured source manifest.
        inventory (Inventory): Explicit canonical repertoire snapshot supplied by its owner.
        now (int): Actual UTC preparation time.

    Returns:
        State: Unpublished candidates with no read receipts or semantic reviews.
    """
    enrollment = graph.enrollment
    scope = Scope(enrollment.tenant, enrollment.owner, enrollment.extension, graph.revision, fingerprint(files), graph.generation)
    digests = {
        "inventory": fingerprint(inventory),
        "query": fingerprint(QUERY_VERSION),
        "schema": fingerprint(SCHEMA_VERSION),
        **environment(graph, files),
    }
    inputs = tuple(Input("input:" + kind, kind, value, now) for kind, value in sorted(digests.items()))
    sources = {item.path: item for item in files if item.disposition == "source"}
    anchors: list[Anchor] = []
    evidence: list[Evidence] = []
    assertions: list[Assertion] = []
    for tool in sorted(inventory.tools, key=lambda item: item.id):
        key = fingerprint(tool.id)
        selected: tuple[str, ...] = ()
        source = sources.get(tool.reference)
        if source is not None:
            anchor = Anchor("anchor:" + key, source.path, source.digest, 0, source.size, graph.indexer, "repertoire-path-join")
            anchors.append(anchor)
            selected = (anchor.id,)
        item = Evidence("evidence:" + key, "inference", "repertoire:" + tool.id, fingerprint(tool), "repertoire", now, ("input:inventory",))
        evidence.append(item)
        assertions.append(
            Assertion(
                "assertion:" + key,
                tool.id,
                selected,
                tool.purpose,
                "Canonical repertoire entry; implementation conformance unreviewed",
                "inference",
                (item.id,),
                (),
                (),
                (),
                now,
                (tool.name,),
            )
        )
    return State(scope, inventory, inputs, files, tuple(anchors), (), tuple(evidence), tuple(assertions), (), (), ())
