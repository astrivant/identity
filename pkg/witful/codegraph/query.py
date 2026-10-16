"""
Select bounded attributed graph evidence without injecting an entire graph or adopting instructions.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import TYPE_CHECKING, Literal

import networkx as nx
from attrs import frozen

from witful.codegraph.models import Edge, Graph, Node, validate
from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data

if TYPE_CHECKING:
    from witful.context.models import Limits


@frozen
class CoverageCount:
    """
    Summarize authenticated file dispositions without emitting their source paths.

    Attributes:
        status (str): Explicit extraction or omission category.
        files (int): Number of files with this disposition.
    """

    status: str
    files: int


@frozen
class Result:
    """
    Return qualified evidence and visible incompleteness, never instructions or an approval.

    Attributes:
        extension (str): Selected opaque extension UUID.
        generation (str): Immutable graph build UUID.
        revision (str): Exact source commit for every returned reference.
        nodes (tuple[Node, ...]): Deterministically selected source references.
        edges (tuple[Edge, ...]): Inspected relationships within the selected view.
        limitations (tuple[str, ...]): Explicit static-analysis and query coverage boundaries.
        truncated (bool): Whether traversal exceeds the configured graph budget.
        freshness (Literal["current"]): Revalidated source state; stale views are not silently served.
        languages (tuple[str, ...]): Actual SDK-detected language identifiers.
        coverage (tuple[CoverageCount, ...]): Complete file counts by extraction or omission category.
    """

    extension: str
    generation: str
    revision: str
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    limitations: tuple[str, ...]
    truncated: bool
    freshness: Literal["current"] = "current"
    languages: tuple[str, ...] = ()
    coverage: tuple[CoverageCount, ...] = ()


def select(graph: Graph, symbol: str, direction: Literal["symbol", "callers", "impact"], limits: Limits, depth: int) -> Result:
    """
    Traverse a finite view using the project's graph library and context byte/token budgets.

    Args:
        graph (Graph): Authenticated complete generation.
        symbol (str): Exact symbol name or local ID, treated as data.
        direction (Literal["symbol", "callers", "impact"]): Selected lookup relation.
        limits (Limits): Existing context limits; UTF-8 bytes conservatively bound tokenizer usage.
        depth (int): Maximum dependency hops; zero selects only matching symbols.

    Returns:
        Result: Qualified evidence fitting both complete serialized output budgets.
    """
    validate(graph)
    if not symbol or len(symbol.encode()) > 4096 or direction not in {"symbol", "callers", "impact"}:
        raise NativeError("invalid")
    if depth < 0 or min(limits.nodes, limits.edges, limits.text_bytes, limits.tokens) < 1:
        raise NativeError("invalid")
    nodes = {node.id: node for node in graph.nodes}
    seeds = sorted(node.id for node in graph.nodes if node.name == symbol or node.id == symbol)
    selected: set[str] = set(seeds[: limits.nodes])
    truncated = len(seeds) > limits.nodes
    network: nx.DiGraph[str, dict[str, object], dict[str, object]] = nx.DiGraph()
    network.add_nodes_from(nodes)
    edges = tuple(edge for edge in graph.edges if direction == "impact" or edge.kind == "calls")
    network.add_edges_from((edge.target, edge.source) for edge in edges)
    pending = tuple(sorted(selected))
    inspected = 0
    # Keep breadth-first ordering deterministic and stop at the actual budget boundary.
    for _ in range(depth if direction != "symbol" else 0):
        following: set[str] = set()
        for origin in pending:
            for neighbor in sorted(network.successors(origin)):
                inspected += 1
                if inspected > limits.edges or (neighbor not in selected and len(selected) >= limits.nodes):
                    truncated = True
                    break
                if neighbor not in selected:
                    selected.add(neighbor)
                    following.add(neighbor)
            if truncated:
                break
        pending = tuple(sorted(following))
        if not pending or truncated:
            break
    view = tuple(edge for edge in graph.edges if edge.source in selected and edge.target in selected)
    truncated |= len(view) > limits.edges
    result = Result(
        graph.enrollment.extension,
        graph.generation,
        graph.revision,
        tuple(nodes[key] for key in sorted(selected)),
        view[: limits.edges],
        (
            "static-python-only" if graph.language == "python" else "static-upstream-sdk-languages",
            "sdk-omitted-files" if any(item.coverage == "sdk-omitted" for item in graph.files) else "no-sdk-omissions",
            "file-level-tracking" if any(item.coverage == "file-only" for item in graph.files) else "symbol-extraction",
            "dynamic-calls-may-be-missing",
            "depth-bounded",
            "no-source-snippets",
            "unresolved-references" if graph.unresolved else "missing-edge-is-not-proof-of-absence",
            "untracked-files-omitted" if graph.omitted_untracked else "tracked-snapshot-only",
            "excluded-or-unsupported-files" if any(item.coverage != "indexed" for item in graph.files) else "indexed-files-only",
        ),
        truncated,
        languages=tuple(sorted({item.language for item in graph.files if item.language and item.language != "unknown"})),
        coverage=tuple(CoverageCount(status, count) for status, count in sorted(Counter(item.coverage for item in graph.files).items())),
    )
    # Never return a JSON prefix or silently remove references merely to fit a prompt.
    if len(json.dumps(as_data(result), ensure_ascii=True, separators=(",", ":")).encode()) > min(limits.tokens, limits.text_bytes):
        raise NativeError("incomplete")
    return result
