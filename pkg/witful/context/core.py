"""
Resolve deterministic working coverage with explicit inputs and no filesystem, clock, network, or execution effects.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from attrs import evolve

from witful.context.graph import enumerate_context, ordered, validate
from witful.context.models import Candidate, Receipt
from witful.knowledge.compiler import lineage
from witful.knowledge.contracts import as_data
from witful.knowledge.models import Insight, Lesson

if TYPE_CHECKING:
    from witful.context.models import Decision, Descriptor, Mapping, Observation, Rule
    from witful.knowledge.models import Identity


def digest(value: object) -> str:
    """
    Hash a structured value without insertion-order or platform-dependent whitespace.

    Args:
        value (object): JSON-compatible object or typed contract root.

    Returns:
        str: SHA-256 of canonical UTF-8 JSON.
    """
    return hashlib.sha256(json.dumps(as_data(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def normalized(term: str) -> str:
    """
    Normalize exact reviewed aliases without semantic inference.

    Args:
        term (str): Bounded task vocabulary term.

    Returns:
        str: NFKC, casefolded, collapsed-whitespace spelling.
    """
    return " ".join(unicodedata.normalize("NFKC", term).casefold().split())


def matches(rule: Rule, descriptor: Descriptor) -> bool:
    """
    Conjoin populated selector dimensions and retain every matching rule.

    Args:
        rule (Rule): Reviewed additive mapping.
        descriptor (Descriptor): Current task metadata.

    Returns:
        bool: Any value within each populated dimension matches.
    """
    return (
        (not rule.tags or bool(set(rule.tags) & set(descriptor.tags)))
        and (not rule.phases or descriptor.phase in rule.phases)
        and (not rule.actions or descriptor.action in rule.actions)
        and (not rule.resources or bool(set(rule.resources) & set(descriptor.resources)))
        and (not rule.paths or any(fnmatchcase(path, pattern) for path in descriptor.paths for pattern in rule.paths))
        and (not rule.terms or bool({normalized(term) for term in rule.terms} & {normalized(term) for term in descriptor.terms}))
    )


def _finish(receipt: Receipt) -> Receipt:
    """
    Bind deterministic content separately from operational observation timestamps.

    Args:
        receipt (Receipt): Completed immutable coverage result.

    Returns:
        Receipt: Content-addressed result with unchanged coverage.
    """
    data = as_data(receipt)
    for field in ("content_digest", "observed_at", "verified_at", "elapsed_ms"):
        data.pop(field)
    return evolve(receipt, content_digest=digest(data))


def _validate_inputs(mapping: Mapping, descriptor: Descriptor, observation: Observation) -> None:
    """
    Reject ambiguous sidecars and invalid caller metadata before traversal.

    Args:
        mapping (Mapping): Reviewed mapping and profile.
        descriptor (Descriptor): Current step.
        observation (Observation): Independent freshness/cost observations.

    Returns:
        None: The input domains support deterministic interpretation.

    Raises:
        ValueError: Required bindings, bounds, selectors, or timestamps are invalid.
    """
    required = (
        *as_data(descriptor.scope).values(),
        descriptor.task,
        descriptor.phase,
        descriptor.action,
        descriptor.context_id,
        descriptor.refresh_trigger,
    )
    if any(not isinstance(value, str) or not value.strip() or len(value.encode()) > 1024 for value in required):
        raise ValueError("Invalid scope or task binding")
    for items in (descriptor.tags, descriptor.paths, descriptor.terms, descriptor.resources, descriptor.concepts):
        if len(items) > 128 or any(not item.strip() or len(item.encode()) > 1024 for item in items):
            raise ValueError("Unbounded task selectors")
    if any(PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts or "\\" in path for path in descriptor.paths):
        raise ValueError("Task paths must be relative POSIX paths")
    if any(
        len(value.encode()) > 1024
        for value in (descriptor.evidence_revision, descriptor.instance, descriptor.sleeve, descriptor.prior_receipt)
    ):
        raise ValueError("Unbounded runtime bindings")
    limits = as_data(mapping.limits)
    if any(value < 0 for value in limits.values() if type(value) is int):
        raise ValueError("Negative budget")
    if observation.observed_at < 0 or observation.verified_at < observation.observed_at:
        raise ValueError("Invalid observation times")
    if observation.source_reads < 0 or observation.elapsed_ms < 0:
        raise ValueError("Invalid observed costs")
    if not observation.source_revision.strip() or not observation.workspace_digest.strip():
        raise ValueError("Missing source or workspace binding")
    if len({rule.id for rule in mapping.rules}) != len(mapping.rules):
        raise ValueError("Duplicate rules")
    for rule in mapping.rules:
        if not rule.id.strip() or not rule.source.strip() or not rule.concepts:
            raise ValueError("Rules need identifiers, targets, and provenance")
        if not any((rule.tags, rule.paths, rule.phases, rule.actions, rule.resources, rule.terms)):
            raise ValueError("Use explicit globals for unconditional constraints")


def resolve(
    identity: Identity,
    mapping: Mapping,
    descriptor: Descriptor,
    observation: Observation,
    decisions: tuple[Decision, ...] = (),
) -> Receipt:
    """
    Compute a bounded working-context receipt without authorizing an action.

    Args:
        identity (Identity): Authorized compiled source snapshot.
        mapping (Mapping): Independently reviewed scope, rules, global requirements and budgets.
        descriptor (Descriptor): Current task context, not a raw prompt.
        observation (Observation): Explicit source/workspace/time observations.
        decisions (tuple[Decision, ...]): Individual reviewed applicability dispositions.

    Returns:
        Receipt: Complete, incomplete, unmapped, or invalid local coverage; always advisory.
    """
    # Denial precedes graph inspection, hashing, labels, counts, and matching.
    if mapping.scope != descriptor.scope or identity.id != mapping.scope.identity:
        return _finish(Receipt("", "", "invalid", blockers=("access_unavailable",)))
    try:
        _validate_inputs(mapping, descriptor, observation)
        nodes, parents, historical = validate(identity)
        if mapping.hierarchy_digest != digest(identity):
            return _finish(Receipt("", "", "invalid", blockers=("mapping_source_changed",)))
        targets = set(mapping.global_concepts) | set(descriptor.concepts) | {target for rule in mapping.rules for target in rule.concepts}
        if targets - nodes.keys():
            raise ValueError("Missing mapping targets")
        judged = {decision.id: decision for decision in decisions}
        if len(judged) != len(decisions) or any(not decision.reason.strip() or not decision.source.strip() for decision in decisions):
            raise ValueError("Duplicate or unsourced decisions")
    except ValueError:
        return _finish(Receipt("", "", "invalid", blockers=("invalid_local_contract",)))

    binding = digest(
        {
            "resolver": "context-v1",
            "hierarchy": mapping.hierarchy_digest,
            "mapping": as_data(mapping),
            "descriptor": as_data(descriptor),
            "revision": observation.source_revision,
            "workspace": observation.workspace_digest,
            "observed_at": observation.observed_at,
            "live_evidence": observation.live_evidence,
            "offline": observation.offline,
        }
    )
    base = Receipt(
        binding,
        "",
        "incomplete",
        descriptor=descriptor,
        hierarchy_digest=mapping.hierarchy_digest,
        mapping_digest=digest(mapping),
        source_revision=observation.source_revision,
        workspace_digest=observation.workspace_digest,
        limits=mapping.limits,
        source_reads=observation.source_reads,
        elapsed_ms=observation.elapsed_ms,
        next_action=descriptor.action,
        observed_at=observation.observed_at,
        verified_at=observation.verified_at,
        offline=observation.offline,
    )
    limits = mapping.limits
    blockers: list[str] = []
    for exceeded, code in (
        (len(identity.relations) > limits.edges, "budget_edges"),
        (observation.source_reads > limits.source_reads, "budget_source_reads"),
        (observation.elapsed_ms > limits.elapsed_ms, "budget_elapsed_ms"),
        (bool(limits.max_age_seconds) and observation.verified_at - observation.observed_at > limits.max_age_seconds, "source_stale"),
        (limits.require_live and (observation.offline or not observation.live_evidence.strip()), "live_evidence_unavailable"),
    ):
        if exceeded:
            blockers.append(code)
    if blockers:
        return _finish(evolve(base, blockers=tuple(blockers)))

    matched = tuple(rule for rule in sorted(mapping.rules, key=lambda item: (item.priority, item.id)) if matches(rule, descriptor))
    task_seeds = set(descriptor.concepts) | {target for rule in matched for target in rule.concepts}
    seeds = task_seeds | set(mapping.global_concepts)
    if not task_seeds:
        return _finish(
            evolve(
                base, state="unmapped", seeds=tuple(sorted(seeds)), blockers=("no_local_guidance" if len(nodes) == 1 else "task_unmapped",)
            )
        )
    paths, required, core, omitted = enumerate_context(identity, seeds, judged, limits)
    outside = judged.keys() - paths.keys()
    if outside and (not omitted or outside - nodes.keys()):
        return _finish(evolve(base, state="invalid", blockers=("decisions_outside_candidates",)))
    if omitted:
        blockers.append("budget_nodes")
    unmet = set(omitted) | outside
    candidates: list[Candidate] = []
    loaded: list[str] = []
    total_bytes = 0

    for identifier in ordered(identity, set(paths)):
        node, decision = nodes[identifier], judged.get(identifier)
        status = "historical" if identifier in historical else decision.status if decision else "pending"
        reason = "Explicitly superseded source lineage" if status == "historical" else decision.reason if decision else ""
        item = Candidate(
            identifier,
            parents.get(identifier),
            type(node).__name__,
            node.name,
            status,
            identifier in required,
            tuple(sorted(paths[identifier])),
            reason,
            decision.source if decision else "",
        )
        if identifier in historical:
            if identifier in required or decision is not None:
                unmet.add(identifier)
                blockers.append("historical_requirement_conflict")
            candidates.append(item)
            continue
        if (
            status in {"pending", "blocked"}
            or (identifier in required and status != "applicable")
            or (identifier in core and status == "deferred")
        ):
            unmet.add(identifier)
        if status in {"applicable", "blocked"}:
            if any(
                ancestor in judged and judged[ancestor].status in {"not_applicable", "deferred"}
                for ancestor in lineage(identifier, parents)[1:]
            ):
                unmet.add(identifier)
                blockers.append("parent_applicability_conflict")
        if status == "applicable":
            statement = node.statement if isinstance(node, (Lesson, Insight)) else ""
            source = node.source if isinstance(node, (Lesson, Insight)) else ""
            size = len(statement.encode()) + len(source.encode())
            if total_bytes + size > limits.text_bytes or total_bytes + size > limits.tokens:
                unmet.add(identifier)
                blockers.append("budget_text_bytes" if total_bytes + size > limits.text_bytes else "budget_tokens")
            else:
                total_bytes += size
                loaded.append(identifier)
                item = evolve(item, statement=statement, source=source, text_digest=digest({"statement": statement, "source": source}))
        candidates.append(item)
    # Account for metadata and review provenance as well as statements; the receipt is not a free token channel.
    context_bytes = len(
        json.dumps(
            {
                "descriptor": as_data(descriptor),
                "candidates": [as_data(item) for item in candidates],
                "seeds": sorted(seeds),
                "rules": [rule.id for rule in matched],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    )
    if context_bytes > limits.tokens:
        blockers.append("budget_tokens")
        unmet.update(loaded)
    if unmet and not blockers:
        blockers.append("applicability_incomplete")
    return _finish(
        evolve(
            base,
            state="incomplete" if unmet or blockers else "complete",
            next_action=descriptor.action if unmet or blockers else "",
            matched_rules=tuple(rule.id for rule in matched),
            seeds=tuple(sorted(seeds)),
            candidates=tuple(candidates),
            loaded=tuple(loaded),
            unmet=tuple(sorted(unmet)),
            blockers=tuple(sorted(set(blockers))),
            text_bytes=total_bytes,
            context_bytes=context_bytes,
        )
    )


def check(receipt: Receipt, current: Receipt, *, context_present: bool) -> tuple[str, ...]:
    """
    Revalidate a receipt against independently refreshed inputs and actual retained context.

    Args:
        receipt (Receipt): Previously stored receipt; its claims are untrusted.
        current (Receipt): Result recomputed from current source, mapping, descriptor and observations.
        context_present (bool): Explicit runtime attestation that exact loaded text is still available.

    Returns:
        tuple[str, ...]: Stale, incomplete or unavailable-context diagnostics; empty still grants no action authority.
    """
    errors: list[str] = []
    if (
        receipt.binding != current.binding
        or _finish(receipt).content_digest != receipt.content_digest
        or receipt.content_digest != current.content_digest
    ):
        errors.append("receipt_changed")
    if current.state != "complete" or receipt.state != "complete":
        errors.append("coverage_incomplete")
    if not context_present:
        errors.append("context_reload_required")
    return tuple(errors)
