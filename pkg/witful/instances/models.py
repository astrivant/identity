"""
Define append-only instance provenance without changing native knowledge or Life schemas.
"""

from __future__ import annotations

from typing import Literal

from attrs import frozen


@frozen
class Provenance:
    """
    Distinguish observed source state from a clean committed definition.

    Attributes:
        revision (str | None): Full Git HEAD, or unknown when unavailable.
        dirty (bool | None): Whether tracked or untracked files differ, or unknown.
        template_revision (str | None): Explicitly supplied upstream template commit.
        package_version (str): Installed Witful version, or unknown.
    """

    revision: str | None = None
    dirty: bool | None = None
    template_revision: str | None = None
    package_version: str = "unknown"


@frozen
class Instance:
    """
    Identify an observed runtime or logical session without guessing platform boundaries.

    Attributes:
        id (str): Random UUID allocated once for this explicit boundary.
        identity_id (str): Native catalog identity shared across instances.
        boundary_id (str): Caller-observed stable boundary key, never an inferred timestamp.
        boundary_kind (Literal["runtime", "logical-session"]): Strength of the supplied boundary evidence.
        session_id (str | None): Optional parent logical session, distinct from the instance UUID.
        served_model (str | None): Authoritative served model, or unknown.
        model_evidence (str | None): Runtime evidence supporting the served model, excluding credentials.
        requested_model (str | None): Configuration request, never proof of the served model.
        provenance (Provenance): Definition and template provenance at the boundary.
        parent_instance_id (str | None): Existing local instance that launched this child.
        predecessor_instance_id (str | None): Existing local runtime explicitly replaced or restored.
    """

    id: str
    identity_id: str
    boundary_id: str
    boundary_kind: Literal["runtime", "logical-session"]
    session_id: str | None = None
    served_model: str | None = None
    model_evidence: str | None = None
    requested_model: str | None = None
    provenance: Provenance = Provenance()
    parent_instance_id: str | None = None
    predecessor_instance_id: str | None = None


@frozen
class Evidence:
    """
    Reference retained native sources without copying them into the instance journal.

    Attributes:
        snapshot_id (str | None): Native Life knowledge snapshot, when successfully captured.
        life_head (str | None): Exact native Life journal prefix; None means no decisions.
        checkpoint_id (str | None): Existing native project checkpoint head, when present.
        gaps (tuple[str, ...]): Explicit missing evidence; never replaced by invented history.
    """

    snapshot_id: str | None = None
    life_head: str | None = None
    checkpoint_id: str | None = None
    gaps: tuple[str, ...] = ()


@frozen
class Task:
    """
    Retain a bounded task handoff rather than reconstructing an unfinished plan from chat.

    Attributes:
        id (str): Stable caller-selected task key.
        status (Literal["pending", "running", "blocked", "succeeded", "failed", "cancelled"]): Recorded task state.
        summary (str): Concise durable scope, excluding secrets and hidden reasoning.
        source (str): Evidence or user-authorized source reference.
        previous (str | None): Exact preceding task event ID for compare-and-set updates.
    """

    id: str
    status: Literal["pending", "running", "blocked", "succeeded", "failed", "cancelled"]
    summary: str
    source: str
    previous: str | None = None


@frozen
class Audit:
    """
    Correlate one actual action with its request and provider trace when available.

    Attributes:
        action (str): Bounded action name; never raw tool arguments or message contents.
        outcome (str): Observed result, including uncertain outcomes.
        request_id (str | None): Existing request correlation identifier.
        trace_id (str | None): Existing 16-byte trace ID as lowercase hexadecimal.
        span_id (str | None): Existing 8-byte span ID as lowercase hexadecimal.
    """

    action: str
    outcome: str
    request_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None


@frozen
class Event:
    """
    Hash-chain lifecycle, task reconciliation, observations, and audit records.

    Attributes:
        id (str): Canonical SHA-256 content ID.
        previous (str | None): Prior event in the complete sidecar journal.
        recorded_at (str): Actual timezone-aware observation time.
        instance_id (str): Existing instance UUID, or the UUID introduced by start.
        operation_id (str): Caller-selected retry key scoped to the instance.
        kind (Literal["start", "reconcile", "task", "audit", "observe", "stop"]): Event discriminator.
        instance (Instance | None): Immutable metadata on start only.
        evidence (Evidence | None): Native snapshot references on start and observe.
        task (Task | None): Task transition on task events only.
        audit (Audit | None): Correlation details on audit events only.
        coverage (Literal["incomplete", "complete"] | None): Explicit startup reconciliation coverage.
        coverage_source (str | None): Evidence supporting the claimed reconciliation coverage.
        pending (tuple[str, ...]): Outstanding task event IDs visible at reconciliation.
        version (Literal[1]): Supported sidecar schema version.
    """

    id: str
    previous: str | None
    recorded_at: str
    instance_id: str
    operation_id: str
    kind: Literal["start", "reconcile", "task", "audit", "observe", "stop"]
    instance: Instance | None = None
    evidence: Evidence | None = None
    task: Task | None = None
    audit: Audit | None = None
    coverage: Literal["incomplete", "complete"] | None = None
    coverage_source: str | None = None
    pending: tuple[str, ...] = ()
    version: Literal[1] = 1
