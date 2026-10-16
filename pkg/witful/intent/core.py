"""
Resolve bounded intent projections and complete witnesses with no network, clock or execution side effects.
"""

from __future__ import annotations

import json
import unicodedata
from typing import TYPE_CHECKING, Literal

import networkx as nx
from attrs import evolve

from witful.exceptions import NativeError
from witful.intent.contracts import network, review_binding, validate
from witful.intent.models import Claim, Result
from witful.knowledge.contracts import as_data

if TYPE_CHECKING:
    from witful.context.models import Limits
    from witful.intent.models import Query, State


def normalized(value: str) -> str:
    """
    Normalize literal discovery vocabulary without interpreting instructions or expressions.

    Args:
        value (str): Caller or approved alias text.

    Returns:
        str: Case-folded NFKC text with stable whitespace.
    """
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def affected(state: State, changed: tuple[str, ...]) -> tuple[str, ...]:
    """
    Compute the deterministic reverse transitive invalidation closure.

    Args:
        state (State): Validated scoped source.
        changed (tuple[str, ...]): Exact changed input or record IDs.

    Returns:
        tuple[str, ...]: Stable closure including the named inputs.
    """
    graph = network(state)
    result = set(changed)
    for value in changed:
        if value not in graph:
            raise NativeError("denied")
        result.update(nx.ancestors(graph, value))
    return tuple(sorted(result))


def bounded(result: Result, limits: Limits) -> Result:
    """
    Refuse the complete result instead of truncating mandatory evidence or source text.

    Args:
        result (Result): Complete candidate response.
        limits (Limits): Explicit query resource contract.

    Returns:
        Result: Complete candidate or a minimal incomplete response fitting the same output bounds.
    """
    bound = min(limits.text_bytes, limits.tokens)
    candidate = evolve(result, limits=limits)
    for _ in range(8):
        size = len(json.dumps(as_data(candidate), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode())
        if size > bound:
            if candidate.result == "incomplete" and candidate.scope is None:
                raise NativeError("incomplete")
            candidate = Result("incomplete", None, limits=limits, limitations=("output-budget",))
            continue
        if size == candidate.output_bytes:
            return candidate
        candidate = evolve(candidate, output_bytes=size)
    raise NativeError("incomplete")


def resolve(state: State, query: Query, limits: Limits, now: int) -> Result:
    """
    Return evidence-qualified discovery, never permission or strict operational readiness.

    Args:
        state (State): Admitted immutable source generation.
        query (Query): Literal selection and independent current observations.
        limits (Limits): Finite traversal and serialized output budgets.
        now (int): UTC observation boundary injected by the caller.

    Returns:
        Result: Complete, incomplete or opaque blocked discovery with independent authority fields.
    """
    validate(state)
    if now < 0 or min(limits.nodes, limits.edges, limits.text_bytes, limits.tokens, limits.elapsed_ms) < 1:
        raise NativeError("invalid")
    if len(query.value.encode()) > limits.text_bytes:
        return bounded(Result("incomplete", None), limits)
    graph = network(state)
    if len(graph) > limits.nodes or graph.number_of_edges() > limits.edges:
        return bounded(Result("incomplete", None, limitations=("traversal-budget",)), limits)
    known = {
        item.id
        for group in (state.inputs, state.anchors, state.coverage, state.evidence, state.assertions, state.reviews, state.requirements)
        for item in group
    }
    if query.operation == "affected":
        if not set(query.changed) <= known:
            return bounded(Result("blocked", None), limits)
        return bounded(Result("complete", state.scope, affected=affected(state, query.changed)), limits)
    inputs = {item.id: item for item in state.inputs}
    observations = {item.id: item for item in query.observations}
    if len(observations) != len(query.observations) or not set(observations) <= set(inputs):
        raise NativeError("invalid")
    stale: set[str] = set()
    unknown: set[str] = set()
    for item in state.inputs:
        observed = observations.get(item.id)
        if observed is not None and (observed.observed > now or observed.observed < item.observed):
            raise NativeError("invalid")
        if item.observed > now or (item.expires is not None and now >= item.expires):
            stale.add(item.id)
        if observed is not None and observed.digest != item.digest:
            stale.add(item.id)
        if item.live and (observed is None or observed.observed != now):
            unknown.add(item.id)
    stale_nodes = set(affected(state, tuple(sorted(stale))))
    unknown_nodes = set(affected(state, tuple(sorted(unknown))))
    latest = {item.assertion: item for item in state.reviews}
    superseded = {prior for item in state.assertions for prior in item.predecessors}
    tools = {item.id: item for item in state.inventory.tools}
    matches: list[Claim] = []
    seeds = set((*state.globals, *query.required))
    vocabulary = normalized(query.value)
    for claim in state.assertions:
        if query.operation == "coverage":
            selected = not query.value or any(anchor == query.value for anchor in claim.anchors)
        elif query.operation == "explain":
            selected = claim.id == query.value
        elif query.operation == "preflight":
            selected = claim.tool == query.value or claim.id == query.value
        else:
            tool = tools.get(claim.tool)
            terms = (claim.id, claim.tool, claim.statement, *claim.aliases, tool.name if tool else "", tool.purpose if tool else "")
            selected = not vocabulary or any(vocabulary in normalized(term) for term in terms)
        if not selected:
            continue
        review = latest.get(claim.id)
        status = review.result if review else "unreviewed"
        freshness: Literal["current", "stale", "unknown"] = (
            "stale" if claim.id in stale_nodes else "unknown" if claim.id in unknown_nodes else "current"
        )
        if review and review.binding != review_binding(state, claim.id):
            freshness = "stale"
        projection: Literal["verified", "inferred"] = "verified" if status == "supported" else "inferred"
        historical = claim.id in superseded or status in {"disputed", "refuted", "withdrawn"} or freshness != "current"
        if not query.history and (claim.id in superseded or (query.view == "verified" and historical)):
            continue
        if query.view != "both" and query.view != projection:
            continue
        paths = {anchor.path for anchor in state.anchors if anchor.id in claim.anchors}
        receipts = tuple(sorted(item.id for item in state.coverage if paths.intersection(item.files)))
        entrypoint = tools[claim.tool].reference if claim.tool else ""
        matches.append(Claim(claim, entrypoint, projection, status, freshness, receipts))
        seeds.add(claim.id)
        seeds.update(receipts)
        if review:
            seeds.add(review.id)
    if query.operation in {"explain", "preflight"} and not matches:
        return bounded(Result("blocked", None), limits)
    if query.operation == "coverage":
        anchors = [item for item in state.anchors if not query.value or item.id == query.value]
        if query.value and not anchors:
            return bounded(Result("blocked", None), limits)
        paths = {item.path for item in anchors}
        seeds.update(item.id for item in anchors)
        seeds.update(item.id for item in state.coverage if paths.intersection(item.files))
    # Mandatory closure includes all counterevidence, regardless of the selected favorable witness.
    closure = set(seeds)
    for seed in seeds:
        if seed not in known:
            return bounded(Result("blocked", None), limits)
        closure.update(nx.descendants(graph, seed))
    if not closure <= known or any(not item.available for item in state.inputs if item.id in closure):
        disclosed = tuple(sorted(item.id for item in state.requirements if item.id in closure and item.disclose_missing))
        return bounded(Result("blocked", state.scope if disclosed else None, missing=disclosed, readiness="blocked"), limits)
    evidence = {item.id: item for item in state.evidence}
    missing: set[str] = set()
    for requirement in state.requirements:
        if requirement.id not in closure:
            continue
        bundle = next((item for item in requirement.bundles if item.id == requirement.selected), None)
        if bundle is None:
            missing.add(requirement.id)
            continue
        leaves: set[str] = set()
        for member in bundle.members:
            leaves.add(member)
            leaves.update(nx.descendants(graph, member))
        witnesses = [evidence[key] for key in sorted(leaves) if key in evidence]
        origins = [item.origin for item in witnesses]
        if (
            not set(requirement.kinds) <= {item.kind for item in witnesses}
            or (requirement.independent and len(set(origins)) != len(origins))
            or leaves.intersection(stale_nodes | unknown_nodes)
        ):
            missing.add(requirement.id)
    if missing:
        disclosed = tuple(sorted(item.id for item in state.requirements if item.id in missing and item.disclose_missing))
        return bounded(Result("blocked", state.scope if disclosed else None, missing=disclosed, readiness="blocked"), limits)
    horizons = [item.expires for item in state.inputs if item.id in closure and item.expires is not None]
    unavailable_checks = tuple(sorted((stale | unknown).intersection(closure)))
    result = Result(
        "complete",
        state.scope,
        tuple(sorted(matches, key=lambda item: item.assertion.id)),
        tuple(sorted(closure)),
        tuple(sorted((item for item in state.evidence if item.id in closure), key=lambda item: item.id)),
        tuple(item for item in state.reviews if item.id in closure),
        tuple(sorted((item for item in state.coverage if item.id in closure), key=lambda item: item.id)),
        tuple(sorted((item for item in state.anchors if item.id in closure), key=lambda item: item.id)),
        missing=unavailable_checks,
        horizon=min(horizons) if horizons else None,
        readiness="blocked" if query.operation == "preflight" else "not-evaluated",
    )
    if query.operation == "preflight":
        result = evolve(result, limitations=(*result.limitations, "executor-must-recheck-and-enforce-atomic-preconditions"))
    return bounded(result, limits)
