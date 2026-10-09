"""
Export the same graph semantics for current knowledge and historical replay.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from witful.knowledge.applications import effective_applications
from witful.knowledge.contracts import as_data
from witful.knowledge.metrics import graph_edges, usage

if TYPE_CHECKING:
    from collections.abc import Sequence

    from witful.knowledge.models import Application, Identity

__all__ = ["graph_data"]


def graph_data(identity: Identity, applications: Sequence[Application]) -> dict[str, object]:
    """
    Compute the complete graph representation from explicit source inputs.

    Args:
        identity (Identity): Compiled current or historical hierarchy.
        applications (Sequence[Application]): Observed uses from the same source snapshot.

    Returns:
        dict[str, object]: JSON-compatible graph with explicit event and effective observation counts.
    """
    counts = usage(identity, applications)
    return {
        "identity": as_data(identity),
        "usage": {key: as_data(count) for key, count in counts.items()},
        "edges": [as_data(edge) for edge in graph_edges(identity, applications)],
        "application_observations": len(applications),
        "effective_applications": len(effective_applications(applications)),
    }
