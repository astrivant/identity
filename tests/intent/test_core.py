"""
Exercise independent evidence dimensions, mandatory closure and bounded deterministic discovery.
"""

from __future__ import annotations

import hashlib

import pytest
from attrs import evolve
from witful.context.models import Limits
from witful.exceptions import NativeError
from witful.intent.contracts import extends, fingerprint, review_binding, validate
from witful.intent.core import affected, resolve
from witful.intent.models import Bundle, Dependency, Evidence, Query, Requirement, Review, Span
from witful.knowledge.contracts import as_data
from witful.native.models import parse

from tests.intent.support import example

LIMITS = Limits(tokens=100000)


def test_no_automatic_verification() -> None:
    """
    Keep declaration evidence, full semantic reading and inferred intent distinct.

    Returns:
        None: Only an explicit supported review changes the projection.
    """
    state = example()
    assert parse(as_data(state), type(state)) == state
    result = resolve(state, Query("find", "publish"), LIMITS, 101)
    assert result.result == "complete"
    assert result.claims[0].projection == "inferred"
    assert result.claims[0].conformance == "unknown"
    review = Review(
        "review:1",
        "claim:publish",
        "maintained-intent/1",
        ("evidence:contract",),
        "supported",
        "Narrow contract matches",
        "a" * 64,
        "fixture-grant",
        101,
    )
    review = evolve(review, binding=review_binding(state, review.assertion))
    reviewed = evolve(state, reviews=(review,))
    assert resolve(reviewed, Query("find", view="verified"), LIMITS, 102).claims[0].projection == "verified"
    assert resolve(reviewed, Query("preflight", "tool:publish"), LIMITS, 102).readiness == "blocked"
    assert resolve(reviewed, Query("find"), LIMITS, 102).execution_authority == "not-evaluated"
    assert resolve(reviewed, Query("find"), LIMITS, 102) == resolve(reviewed, Query("find"), LIMITS, 102)
    assert fingerprint(state) == fingerprint(example())


@pytest.mark.parametrize("method", ["retrieved", "parsed", "summarized", "truncated"])
def test_ingestion_is_not_inspection(method: str) -> None:
    """
    Reject read receipts that convert ingestion into semantic inspection.

    Args:
        method (str): Nonsemantic source-processing method.

    Returns:
        None: Every misleading receipt fails the closed contract.
    """
    state = example()
    receipt = as_data(state.coverage[0])
    assert isinstance(receipt, dict)
    receipt["method"] = method
    with pytest.raises(NativeError):
        validate(evolve(state, coverage=(parse(receipt, type(state.coverage[0])),)))


@pytest.mark.parametrize(
    "spans",
    [(), (Span("contract.md", 1, 10, "inspected"),), (Span("contract.md", 0, 20, "inspected"), Span("contract.md", 10, 28, "inspected"))],
)
def test_coverage_partition(spans: tuple[Span, ...]) -> None:
    """
    Reject missing, overlapping and shifted coverage denominators.

    Args:
        spans (tuple[Span, ...]): Invalid partition of the exact file universe.

    Returns:
        None: No partial range is presented as a complete receipt.
    """
    state = example()
    with pytest.raises(NativeError):
        validate(evolve(state, coverage=(evolve(state.coverage[0], spans=spans),)))


def test_partial_coverage_can_support_narrow_intent() -> None:
    """
    Preserve narrow reviewed intent without claiming full implementation inspection.

    Returns:
        None: Coverage and conformance remain independent of the supported review.
    """
    state = example()
    receipt = evolve(
        state.coverage[0], spans=(Span("contract.md", 0, 7, "inspected"), Span("contract.md", 7, state.files[0].size, "uninspected"))
    )
    review = Review(
        "review:1", "claim:publish", "narrow/1", ("evidence:contract",), "supported", "Declared intent only", "a" * 64, "grant", 101
    )
    state = evolve(state, coverage=(receipt,))
    review = evolve(review, binding=review_binding(state, review.assertion))
    state = evolve(state, reviews=(review,))
    result = resolve(state, Query("find", view="verified"), LIMITS, 102)
    assert result.claims[0].coverage == (receipt.id,)
    assert result.coverage[0].spans[1].state == "uninspected"


def test_complete_witnesses_and_counterevidence() -> None:
    """
    Require a whole selected AND witness and preserve contradictions outside that choice.

    Returns:
        None: Favorable alternatives cannot hide counterevidence or combine partial witnesses.
    """
    state = example()
    test = Evidence("test:1", "test_result", "test://exact-run", "b" * 64, "test-run", 100, ("parser",))
    counter = evolve(test, id="counter:1", source="test://failing-run", origin="failing-run")
    requirement = Requirement(
        "requirement:1",
        "contract-and-test/1",
        (Bundle("a", ("evidence:contract", "test:1")), Bundle("b", ("missing:contract", "counter:1"))),
        "a",
        ("intent_declaration", "test_result"),
        True,
    )
    state = evolve(
        state,
        evidence=(*state.evidence, test, counter),
        requirements=(requirement,),
        assertions=(evolve(state.assertions[0], counter=(counter.id,)),),
        dependencies=(Dependency("claim:publish", (requirement.id,)),),
    )
    result = resolve(state, Query("find"), LIMITS, 101)
    assert result.result == "complete"
    assert {item.id for item in result.evidence} == {"test:1", "counter:1", "evidence:contract"}
    assert resolve(evolve(state, requirements=(evolve(requirement, selected="b"),)), Query("find"), LIMITS, 101).result == "blocked"
    assert resolve(evolve(state, requirements=(evolve(requirement, selected=""),)), Query("find"), LIMITS, 101).result == "blocked"
    dependent = evolve(test, origin="maintainer-contract")
    assert resolve(evolve(state, evidence=(state.evidence[0], dependent, counter)), Query("find"), LIMITS, 101).result == "blocked"


def test_cycle_missing_budget_and_invalidation() -> None:
    """
    Reject circular justification, opaque missing requirements and silent budget pruning.

    Returns:
        None: Bounded failures preserve their distinction from complete discovery.
    """
    state = example()
    cyclic = evolve(state, dependencies=(Dependency("evidence:contract", ("claim:publish",)),))
    with pytest.raises(NativeError):
        validate(cyclic)
    missing = resolve(evolve(state, dependencies=(Dependency("claim:publish", ("private:unknown",)),)), Query("find"), LIMITS, 101)
    assert missing.result == "blocked" and missing.scope is None and missing.witnesses == ()
    assert resolve(state, Query("find"), evolve(LIMITS, nodes=1), 101).result == "incomplete"
    assert resolve(state, Query("find"), evolve(LIMITS, tokens=1000), 101).result == "incomplete"
    invalidated = affected(state, ("parser",))
    assert "claim:publish" in invalidated and "anchor:contract" in invalidated
    assert affected(state, ("parser", "parser")) == invalidated


def test_stale_review_withdrawal_and_append_only() -> None:
    """
    Retain historic promotion while excluding stale or withdrawn current verification.

    Returns:
        None: Review history is immutable and input freshness remains independently visible.
    """
    state = example()
    review = Review("review:1", "claim:publish", "intent/1", ("evidence:contract",), "supported", "Declared", "a" * 64, "grant", 101)
    state = evolve(state, inputs=(evolve(state.inputs[0], expires=102), *state.inputs[1:]))
    review = evolve(review, binding=review_binding(state, review.assertion))
    state = evolve(state, reviews=(review,))
    assert resolve(state, Query("find", view="verified"), LIMITS, 102).claims == ()
    result = resolve(state, Query("find", view="verified", history=True), LIMITS, 102)
    assert result.claims[0].freshness == "stale"
    withdrawn = evolve(review, id="review:2", result="withdrawn", predecessor=review.id)
    updated = evolve(state, reviews=(review, withdrawn))
    extends(state, updated)
    assert resolve(updated, Query("find", history=True), LIMITS, 101).claims[0].verification == "withdrawn"
    with pytest.raises(NativeError):
        extends(updated, state)


def test_exact_mandatory_teaching() -> None:
    """
    Retain exact required instruction bytes instead of substituting an inferred summary.

    Returns:
        None: Exact text survives closure and truncation never removes it silently.
    """
    state = example()
    text = "Review the exact staged paths before publishing."
    teaching = Evidence(
        "lesson:required",
        "mandatory_teaching",
        "context:binding",
        hashlib.sha256(text.encode()).hexdigest(),
        "owner-reviewed",
        100,
        (),
        text,
    )
    state = evolve(state, evidence=(*state.evidence, teaching))
    result = resolve(state, Query("find", required=(teaching.id,)), LIMITS, 101)
    assert teaching in result.evidence
    with pytest.raises(NativeError):
        validate(evolve(state, evidence=(*example().evidence, evolve(teaching, text=""))))


def test_review_inputs_cannot_be_silently_renewed() -> None:
    """
    Keep a previous semantic approval stale when configuration changes under the same commit.

    Returns:
        None: An unchanged source SHA does not preserve review validity across changed inputs.
    """
    state = example()
    review = Review(
        "review:1",
        "claim:publish",
        "intent/1",
        ("evidence:contract",),
        "supported",
        "Declared",
        "a" * 64,
        "grant",
        101,
        binding=review_binding(state, "claim:publish"),
    )
    reviewed = evolve(state, reviews=(review,))
    changed = evolve(
        reviewed, inputs=tuple(evolve(item, digest="f" * 64) if item.kind == "configuration" else item for item in state.inputs)
    )
    assert resolve(changed, Query("find", view="verified"), LIMITS, 102).claims == ()
    assert resolve(changed, Query("find", history=True), LIMITS, 102).claims[0].freshness == "stale"
    assert changed.reviews == reviewed.reviews


def test_exact_output_accounting() -> None:
    """
    Include response metadata in the byte budget, not only the selected statement text.

    Returns:
        None: Reported output bytes match complete compact JSON exactly.
    """
    import json

    result = resolve(example(), Query("find"), LIMITS, 101)
    assert result.output_bytes == len(json.dumps(as_data(result), ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode())
    assert result.limits == LIMITS


@pytest.mark.parametrize("resource", ["worktree", "index", "remote-ref", "git-config", "tool-version", "authentication", "approval"])
def test_live_observations_expire_independently_of_head(resource: str) -> None:
    """
    Keep live readiness distinct from immutable code even when the source commit is unchanged.

    Args:
        resource (str): Explicit observation class required by the selected procedure.

    Returns:
        None: Missing or changed observations are visible and never grant execution authority.
    """
    from witful.intent.models import Input, Observation

    state = example()
    live = Input("observation:" + resource, resource, "b" * 64, 100, 110, True)
    state = evolve(state, inputs=(*state.inputs, live))
    missing = resolve(state, Query("preflight", "tool:publish"), LIMITS, 101)
    assert live.id in missing.missing and missing.claims[0].freshness == "unknown"
    current = Query("preflight", "tool:publish", observations=(Observation(live.id, live.digest, 101),))
    assert resolve(state, current, LIMITS, 101).claims[0].freshness == "current"
    assert resolve(state, current, LIMITS, 101).readiness == "blocked"
    changed = evolve(current, observations=(Observation(live.id, "c" * 64, 101),))
    assert resolve(state, changed, LIMITS, 101).claims[0].freshness == "stale"
    expired = evolve(current, observations=(Observation(live.id, live.digest, 110),))
    assert resolve(state, expired, LIMITS, 110).claims[0].freshness == "stale"


def test_release_build_is_not_publication() -> None:
    """
    Name the authorized release obligation without exposing unavailable witness identifiers.

    Returns:
        None: Build evidence alone remains publication-unverified, not proof of a failed release.
    """
    state = example()
    build = Evidence("build", "test_result", "run:build", "b" * 64, "build", 100, ())
    requirement = Requirement(
        "publication_unverified",
        "release-completion/1",
        (Bundle("complete-release", ("build", "tag", "destination", "download", "independent-verification")),),
        "complete-release",
        ("test_result", "runtime_observation"),
        disclose_missing=True,
    )
    state = evolve(state, evidence=(*state.evidence, build), requirements=(requirement,), globals=(requirement.id,))
    result = resolve(state, Query("find"), LIMITS, 101)
    assert result.result == "blocked" and result.missing == ("publication_unverified",)
    assert not result.witnesses and not result.claims


def test_unclaimed_coverage_and_empty_repository() -> None:
    """
    Retrieve reading receipts independently of claims and preserve an honest empty manifest.

    Returns:
        None: No invented capabilities or inspection counts appear.
    """
    state = evolve(example(), assertions=())
    result = resolve(state, Query("coverage", "anchor:contract"), LIMITS, 101)
    assert result.coverage == state.coverage and result.claims == ()
    empty = evolve(state, scope=evolve(state.scope, manifest=fingerprint(())), files=(), anchors=(), coverage=(), evidence=())
    assert resolve(empty, Query("find"), LIMITS, 101).claims == ()


def test_incremental_and_clean_projection_agree() -> None:
    """
    Compare incremental stale-input expansion with an independent clean reconstruction.

    Returns:
        None: Both paths return identical evidence and preserve the original source records.
    """
    state = example()
    before = fingerprint(state)
    changed = evolve(state, inputs=tuple(evolve(item, expires=101) if item.kind == "parser" else item for item in state.inputs))
    invalidated = affected(state, ("parser",))
    clean = parse(as_data(changed), type(changed))
    assert "claim:publish" in invalidated
    assert resolve(changed, Query("find", history=True), LIMITS, 102) == resolve(clean, Query("find", history=True), LIMITS, 102)
    assert fingerprint(state) == before


def test_successor_cannot_hide_predecessor_counterevidence() -> None:
    """
    Retain known contradictions when a new claim supersedes an earlier one.

    Returns:
        None: Selecting only the new claim still carries the original counterevidence.
    """
    state = example()
    counter = Evidence("counter:1", "runtime_observation", "run:failure", "b" * 64, "observed-run", 100, ())
    original = evolve(state.assertions[0], counter=(counter.id,))
    successor = evolve(original, id="claim:successor", counter=(), predecessors=(original.id,), asserted=101)
    state = evolve(state, evidence=(*state.evidence, counter), assertions=(original, successor))
    result = resolve(state, Query("explain", successor.id), LIMITS, 102)
    assert result.claims[0].assertion == successor
    assert counter in result.evidence
