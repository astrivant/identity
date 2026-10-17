"""
Validate exact inspection universes and grounded dependency contracts without judging semantic adequacy.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import networkx as nx

from witful.codegraph.models import digest, relative
from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native.context import identifier
from witful.repertoire.journal import validate as validate_inventory

if TYPE_CHECKING:
    from witful.intent.models import Anchor, Assertion, Coverage, Evidence, Input, Requirement, Review, State

QUERY_VERSION = "intent-query/1"
SCHEMA_VERSION = "intent/1"


def fingerprint(value: object) -> str:
    """
    Hash canonical typed data independently of transport or ciphertext representation.

    Args:
        value (object): Closed serializable value.

    Returns:
        str: SHA-256 of deterministic compact JSON.
    """
    return hashlib.sha256(
        json.dumps(as_data({"value": value}), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def review_binding(state: State, assertion: str) -> str:
    """
    Bind semantic review to exact source, environment, evidence and witness configuration.

    Args:
        state (State): Immutable review input.
        assertion (str): Exact reviewed claim ID.

    Returns:
        str: Canonical digest; appending reviews alone does not invalidate earlier input bindings.
    """
    return fingerprint(
        (
            state.scope,
            state.inventory,
            state.inputs,
            state.files,
            state.anchors,
            state.coverage,
            state.evidence,
            state.assertions,
            state.requirements,
            state.dependencies,
            state.globals,
            assertion,
        )
    )


def records(state: State) -> tuple[Input | Anchor | Coverage | Evidence | Assertion | Review | Requirement, ...]:
    """
    Enumerate the closed record union without losing typed identity fields.

    Args:
        state (State): Scoped immutable intent source.

    Returns:
        tuple[Input | Anchor | Coverage | Evidence | Assertion | Review | Requirement, ...]: All addressable records.
    """
    return (*state.inputs, *state.anchors, *state.coverage, *state.evidence, *state.assertions, *state.reviews, *state.requirements)


def network(state: State) -> nx.DiGraph[str, dict[str, object], dict[str, object]]:
    """
    Compose mandatory edges, retaining unresolved references for opaque blocked diagnostics.

    Args:
        state (State): Structurally validated state.

    Returns:
        nx.DiGraph[str, dict[str, object], dict[str, object]]: Consumer-to-prerequisite graph with frozen witness selections.
    """
    graph: nx.DiGraph[str, dict[str, object], dict[str, object]] = nx.DiGraph()
    graph.add_nodes_from(record.id for record in records(state))
    inspections: tuple[Anchor | Coverage, ...] = (*state.anchors, *state.coverage)
    for inspection in inspections:
        graph.add_edges_from((inspection.id, source.id) for source in state.inputs)
    for claim_id, review in {item.assertion: item for item in state.reviews}.items():
        graph.add_edge(claim_id, review.id)
    for item in state.evidence:
        graph.add_edges_from((item.id, source) for source in item.dependencies)
    for claim in state.assertions:
        # Every claim inherits the scope-wide environment, including inventory and engine versions.
        graph.add_edges_from((claim.id, source.id) for source in state.inputs)
        graph.add_edges_from(
            (claim.id, source) for source in (*claim.anchors, *claim.support, *claim.counter, *claim.dependencies, *claim.predecessors)
        )
    for review in state.reviews:
        graph.add_edges_from((review.id, source) for source in review.sources)
        graph.add_edges_from((review.id, source.id) for source in state.inputs)
    for requirement in state.requirements:
        bundle = next((item for item in requirement.bundles if item.id == requirement.selected), None)
        if bundle is not None:
            graph.add_edges_from((requirement.id, member) for member in bundle.members)
    for dependency in state.dependencies:
        graph.add_edges_from((dependency.consumer, source) for source in dependency.prerequisites)
    return graph


def validate(state: State) -> None:
    """
    Reject ambiguous identities, forged coverage, malformed evidence and circular justification.

    Args:
        state (State): Candidate closed intent generation.

    Returns:
        None: Structural validity only; an authorized reviewer still owns semantic judgments.
    """
    for value in (state.scope.tenant, state.scope.owner, state.scope.repository, state.scope.graph):
        identifier(value)
    if state.scope.owner == state.scope.repository or not digest(state.scope.revision, (40, 64)):
        raise NativeError("invalid")
    if state.scope.schema != SCHEMA_VERSION or state.scope.manifest != fingerprint(state.files):
        raise NativeError("invalid")
    try:
        validate_inventory(state.inventory, (), set())
    except ValueError:
        raise NativeError("invalid") from None
    identifiers = [record.id for record in records(state)]
    if len(set(identifiers)) != len(identifiers) or any(not value or len(value) > 256 for value in identifiers):
        raise NativeError("invalid")
    inputs = {item.id: item for item in state.inputs}
    expected = {"inventory": fingerprint(state.inventory), "query": fingerprint(QUERY_VERSION), "schema": fingerprint(SCHEMA_VERSION)}
    for kind, content in expected.items():
        if len([item for item in state.inputs if item.kind == kind and item.digest == content]) != 1:
            raise NativeError("invalid")
    if not {"parser", "configuration", "dependency-locks"} <= {item.kind for item in state.inputs}:
        raise NativeError("incomplete")
    for item in state.inputs:
        if not digest(item.digest) or item.observed < 0 or (item.expires is not None and item.expires <= item.observed):
            raise NativeError("invalid")
    files = {item.path: item for item in state.files}
    if len(files) != len(state.files) or tuple(sorted(files)) != tuple(item.path for item in state.files):
        raise NativeError("invalid")
    for source_file in state.files:
        relative(source_file.path)
        if not digest(source_file.digest) or source_file.size < 0:
            raise NativeError("invalid")
    anchors = {item.id: item for item in state.anchors}
    for anchor in state.anchors:
        file = files.get(anchor.path)
        if (
            file is None
            or file.digest != anchor.digest
            or not 0 <= anchor.start <= anchor.end <= file.size
            or not anchor.parser
            or not anchor.method
        ):
            raise NativeError("invalid")
    for coverage in state.coverage:
        if (
            coverage.manifest != state.scope.manifest
            or not coverage.inspector
            or not coverage.question
            or coverage.observed < 0
            or len(set(coverage.files)) != len(coverage.files)
            or not set(coverage.files) <= set(files)
            or not {span.path for span in coverage.spans} <= set(coverage.files)
        ):
            raise NativeError("invalid")
        for path in coverage.files:
            position = 0
            for span in sorted((part for part in coverage.spans if part.path == path), key=lambda part: part.start):
                if span.start != position or span.end <= span.start or span.end > files[path].size:
                    raise NativeError("invalid")
                if span.state == "inspected" and (coverage.method != "semantic" or files[path].disposition == "excluded"):
                    raise NativeError("invalid")
                position = span.end
            if position != files[path].size:
                raise NativeError("incomplete")
    evidence = {item.id: item for item in state.evidence}
    for evidence_item in state.evidence:
        if not evidence_item.source or not evidence_item.origin or not digest(evidence_item.digest) or evidence_item.produced < 0:
            raise NativeError("invalid")
        if evidence_item.text and hashlib.sha256(evidence_item.text.encode()).hexdigest() != evidence_item.digest:
            raise NativeError("invalid")
        if evidence_item.kind == "mandatory_teaching" and not evidence_item.text:
            raise NativeError("incomplete")
        if not set(evidence_item.dependencies) <= set(identifiers):
            raise NativeError("invalid")
        if evidence_item.kind == "source_inspection" and not any(
            receipt.id in evidence_item.dependencies and receipt.method == "semantic" for receipt in state.coverage
        ):
            raise NativeError("invalid")
    assertions = {item.id: item for item in state.assertions}
    tools = {item.id for item in state.inventory.tools}
    prior_assertions: set[str] = set()
    for claim in state.assertions:
        if (
            (claim.tool and claim.tool not in tools)
            or not claim.statement
            or not claim.applicability
            or claim.asserted < 0
            or not set(claim.anchors) <= set(anchors)
            or not set((*claim.support, *claim.counter)) <= set(evidence)
            or not set(claim.predecessors) <= prior_assertions
            or not set(claim.dependencies) <= set(identifiers)
        ):
            raise NativeError("invalid")
        prior_assertions.add(claim.id)
    latest: dict[str, str] = {}
    for review in state.reviews:
        if (
            review.assertion not in assertions
            or not review.criterion
            or not review.reason
            or not digest(review.reviewer)
            or not review.authority
            or review.reviewed < 0
            or not digest(review.binding)
            or review.predecessor != latest.get(review.assertion, "")
            or not set(review.sources) <= set(evidence)
        ):
            raise NativeError("invalid")
        if review.result == "supported" and (
            not review.sources or any(evidence[source].kind != "intent_declaration" for source in review.sources)
        ):
            raise NativeError("invalid")
        latest[review.assertion] = review.id
    requirements = {item.id: item for item in state.requirements}
    for requirement in state.requirements:
        bundles = {bundle.id: bundle for bundle in requirement.bundles}
        if (
            len(bundles) != len(requirement.bundles)
            or not requirement.criterion
            or (requirement.selected and requirement.selected not in bundles)
            or any(not bundle.members for bundle in requirement.bundles)
            and not requirement.allow_empty
        ):
            raise NativeError("invalid")
        for bundle in requirement.bundles:
            if len(set(bundle.members)) != len(bundle.members):
                raise NativeError("invalid")
            if any(member in identifiers and member not in evidence and member not in requirements for member in bundle.members):
                raise NativeError("invalid")
    if len({item.consumer for item in state.dependencies}) != len(state.dependencies):
        raise NativeError("invalid")
    if any(item.consumer not in identifiers for item in state.dependencies):
        raise NativeError("invalid")
    if not set(state.globals) <= set(identifiers):
        raise NativeError("invalid")
    graph = network(state)
    if not nx.is_directed_acyclic_graph(graph):
        raise NativeError("invalid")
    # Alternate witnesses must be acyclic too, even when they were not selected for this query.
    for requirement in state.requirements:
        for bundle in requirement.bundles:
            graph.add_edges_from((requirement.id, member) for member in bundle.members)
    if not nx.is_directed_acyclic_graph(graph):
        raise NativeError("invalid")
    if any(not item.kind for item in inputs.values()):
        raise NativeError("invalid")


def extends(previous: State, candidate: State) -> None:
    """
    Preserve immutable records on a same-source refresh; new scopes retain history through native ancestry.

    Args:
        previous (State): Authenticated prior generation.
        candidate (State): Validated proposed successor.

    Returns:
        None: Existing assertions, reviews and receipts have not been overwritten or removed.
    """
    if previous.scope != candidate.scope:
        if (previous.scope.tenant, previous.scope.owner, previous.scope.repository) != (
            candidate.scope.tenant,
            candidate.scope.owner,
            candidate.scope.repository,
        ):
            raise NativeError("denied")
        return
    for before, after in (
        (previous.anchors, candidate.anchors),
        (previous.coverage, candidate.coverage),
        (previous.evidence, candidate.evidence),
        (previous.assertions, candidate.assertions),
        (previous.reviews, candidate.reviews),
    ):
        if after[: len(before)] != before:
            raise NativeError("conflict")
