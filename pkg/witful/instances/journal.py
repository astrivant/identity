"""
Persist durable local runtime provenance with explicit reconciliation and retry boundaries.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

from attrs import evolve

from witful.checkpoints.journal import read as read_checkpoints
from witful.files import replace_file
from witful.instances.models import Audit, Event, Evidence, Instance, Provenance, Task
from witful.knowledge.contracts import as_data, structure
from witful.knowledge.models import Catalog
from witful.life.contracts import canonical, content_id, snapshot_identity
from witful.life.journal import capture_snapshot, read_archive
from witful.life.models import Snapshot

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

_TERMINAL = {"succeeded", "failed", "cancelled"}
_HASH = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def _text(value: str, label: str) -> None:
    """
    Reject blank or unbounded metadata at the source boundary.

    Args:
        value (str): Caller-controlled metadata.
        label (str): Safe field description.

    Returns:
        None: The bounded metadata is valid.
    """
    if not value.strip() or len(value) > 512 or any(ord(char) < 32 for char in value):
        raise ValueError(f"Invalid {label}; require 1-512 printable characters")


def _identifier(value: str, label: str) -> None:
    """
    Restrict correlation labels to bounded identifiers rather than arbitrary tool payloads.

    Args:
        value (str): Caller-supplied opaque identifier.
        label (str): Safe field description.

    Returns:
        None: The identifier fits the closed metadata alphabet.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}", value):
        raise ValueError(f"Invalid {label}; require a bounded opaque identifier")


def pending_tasks(events: Sequence[Event]) -> tuple[Event, ...]:
    """
    Project unfinished tasks across every instance without declaring them abandoned.

    Args:
        events (Sequence[Event]): Validated history or a validated prefix.

    Returns:
        tuple[Event, ...]: Latest pending, running, or blocked event per task, sorted by task ID.
    """
    heads = {event.task.id: event for event in events if event.task is not None}
    return tuple(event for key in sorted(heads) if (event := heads[key]).task is not None and event.task.status not in _TERMINAL)


def validate(events: Sequence[Event]) -> None:
    """
    Reject corrupted chronology, duplicate boundaries, conflicting retries, and stale task handoffs.

    Args:
        events (Sequence[Event]): Complete ordered sidecar history.

    Returns:
        None: Every event respects the immutable source contract.
    """
    instances: dict[str, Instance] = {}
    boundaries: set[tuple[str, str, str]] = set()
    operations: set[tuple[str, str]] = set()
    tasks: dict[str, Event] = {}
    stopped: set[str] = set()
    previous: str | None = None
    prefix: list[Event] = []
    for event in events:
        if event.version != 1 or event.kind not in {"start", "reconcile", "task", "audit", "observe", "stop"}:
            raise ValueError("Unsupported instance event version or kind")
        if event.coverage not in {None, "incomplete", "complete"}:
            raise ValueError("Unsupported reconciliation coverage")
        if event.id != content_id(event) or event.previous != previous:
            raise ValueError("Invalid instance content or history chain")
        if datetime.fromisoformat(event.recorded_at).tzinfo is None:
            raise ValueError("Instance observation time must include a timezone")
        if str(UUID(event.instance_id)) != event.instance_id or UUID(event.instance_id).version != 4:
            raise ValueError("Instance IDs must be canonical random UUIDs")
        _identifier(event.operation_id, "operation ID")
        key = (event.instance_id, event.operation_id)
        if key in operations:
            raise ValueError("Duplicate instance operation")
        operations.add(key)
        if event.kind == "start":
            item = event.instance
            if item is None or item.id != event.instance_id or item.id in instances or event.evidence is None:
                raise ValueError("Invalid instance start")
            if item.boundary_kind not in {"runtime", "logical-session"}:
                raise ValueError("Unsupported boundary kind")
            if item.session_id is not None:
                _identifier(item.session_id, "session ID")
            boundary = (item.identity_id, item.boundary_kind, item.boundary_id)
            if boundary in boundaries:
                raise ValueError("Duplicate observed boundary")
            boundaries.add(boundary)
            for value in (item.identity_id, item.boundary_id):
                _identifier(value, "instance metadata")
            for optional_value in (item.session_id, item.requested_model, item.served_model, item.model_evidence):
                if optional_value is not None:
                    _text(optional_value, "model or session metadata")
            if (item.served_model is None) != (item.model_evidence is None):
                raise ValueError("Served model requires authoritative evidence; otherwise leave both unknown")
            for revision in (item.provenance.revision, item.provenance.template_revision):
                if revision is not None and not _COMMIT.fullmatch(revision):
                    raise ValueError("Revision must be a full Git commit ID or unknown")
            if item.provenance.revision is None and item.provenance.dirty is not None:
                raise ValueError("Dirty state is unknown when Git provenance is unavailable")
            _text(item.provenance.package_version, "package version")
            for ancestor in (item.parent_instance_id, item.predecessor_instance_id):
                if ancestor is not None and ancestor not in instances:
                    raise ValueError("Parent and predecessor must reference existing local instance UUIDs")
            instances[item.id] = item
        elif event.instance_id not in instances or event.instance_id in stopped or event.instance is not None:
            raise ValueError("Unknown or stopped instance, or repeated start metadata")
        if (event.kind in {"start", "observe"}) != (event.evidence is not None):
            raise ValueError("Snapshot evidence belongs only to start or observe")
        if event.evidence is not None:
            evidence = event.evidence
            for identifier in (evidence.snapshot_id, evidence.life_head, evidence.checkpoint_id):
                if identifier is not None and not _HASH.fullmatch(identifier):
                    raise ValueError("Invalid native evidence reference")
            if evidence.snapshot_id is None and not evidence.gaps:
                raise ValueError("Missing native snapshot requires an explicit gap")
            for gap in evidence.gaps:
                _text(gap, "evidence gap")
        if (event.kind == "task") != (event.task is not None) or (event.kind == "audit") != (event.audit is not None):
            raise ValueError("Task or audit payload does not match its event kind")
        if event.task is not None:
            task = event.task
            if task.status not in {"pending", "running", "blocked", "succeeded", "failed", "cancelled"}:
                raise ValueError("Unsupported task state")
            _identifier(task.id, "task ID")
            for value in (task.summary, task.source):
                _text(value, "task metadata")
            head = tasks.get(task.id)
            if task.previous != (head.id if head else None):
                raise ValueError("Task transition must reference its exact previous event")
            if head is not None and head.task is not None and head.task.status in _TERMINAL:
                raise ValueError("Completed tasks are immutable; use a new task ID for new work")
            tasks[task.id] = event
        if event.kind == "audit" or (event.task is not None and event.task.status == "running"):
            require_ready(prefix, event.instance_id)
        if event.audit is not None:
            audit = event.audit
            for value in (audit.action, audit.outcome):
                _identifier(value, "audit metadata")
            if audit.request_id is not None:
                _identifier(audit.request_id, "request ID")
            for identifier, size in ((audit.trace_id, 32), (audit.span_id, 16)):
                if identifier is not None and (not re.fullmatch(f"[0-9a-f]{{{size}}}", identifier) or not int(identifier, 16)):
                    raise ValueError("Trace and span IDs must be nonzero lowercase hexadecimal")
            if audit.span_id is not None and audit.trace_id is None:
                raise ValueError("Span correlation requires its trace ID")
        if event.kind in {"start", "reconcile"}:
            if event.coverage is None or event.pending != tuple(item.id for item in pending_tasks(prefix)):
                raise ValueError("Reconciliation must retain the exact pending task frontier")
            if event.coverage == "complete" and event.coverage_source is None:
                raise ValueError("Complete reconciliation requires a coverage source")
            if event.coverage_source is not None:
                _text(event.coverage_source, "coverage source")
        elif event.coverage is not None or event.coverage_source is not None or event.pending:
            raise ValueError("Coverage belongs only to start or reconcile")
        if event.kind == "stop":
            stopped.add(event.instance_id)
        prefix.append(event)
        previous = event.id


def _owned(root: Path, name: str) -> Path:
    """
    Reject redirected sidecar files instead of writing through external or ambiguous symlinks.

    Args:
        root (Path): Explicit collection root.
        name (str): Package-owned relative filename.

    Returns:
        Path: Confined nonsymlink destination.
    """
    path = root / name
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Instance storage must remain inside its collection")
    return path


def read(root: Path) -> tuple[Event, ...]:
    """
    Read a complete source journal, refusing truncated or blank records rather than repairing history.

    Args:
        root (Path): Collection owning knowledge/instances.jsonl.

    Returns:
        tuple[Event, ...]: Validated ordered events, or empty when no observations exist.
    """
    path = _owned(root, "knowledge/instances.jsonl")
    data = path.read_bytes() if path.exists() else b""
    if data and not data.endswith(b"\n"):
        raise ValueError("Truncated instance journal; preserve and review the original")
    events = tuple(structure(json.loads(line), Event) for line in data.splitlines())
    validate(events)
    return events


@contextmanager
def _locked(root: Path) -> Iterator[tuple[Event, ...]]:
    """
    Serialize writers through the collection-owned instance lock.

    Args:
        root (Path): Existing collection directory.

    Yields:
        tuple[Event, ...]: Validated history protected from cooperating writers.
    """
    with _owned(root, ".instances.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield read(root)


def _durable(path: Path, content: bytes, expected: bytes | None) -> None:
    """
    Atomically publish a source prefix and synchronize its containing directory.

    Args:
        path (Path): Collection-owned file.
        content (bytes): Complete validated bytes.
        expected (bytes | None): Previously observed bytes.

    Returns:
        None: Bytes and directory metadata have been synchronized locally.
    """
    replace_file(path, content, expected=expected)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _append(root: Path, events: tuple[Event, ...], event: Event) -> Event:
    """
    Extend the validated journal without changing any existing byte.

    Args:
        root (Path): Source collection.
        events (tuple[Event, ...]): Previously validated prefix under the writer lock.
        event (Event): New event with an unset content ID.

    Returns:
        Event: Persisted content-addressed event.
    """
    event = evolve(event, id=content_id(event))
    validate((*events, event))
    path = _owned(root, "knowledge/instances.jsonl")
    original = path.read_bytes() if path.exists() else None
    # Validate readback as well: noncooperating edits must not be incorporated silently.
    if read(root) != events:
        raise RuntimeError("Concurrent instance journal edit")
    _durable(path, (original or b"") + canonical(as_data(event)) + b"\n", original)
    return event


def provenance(root: Path, template_revision: str | None = None) -> Provenance:
    """
    Inspect only commit identity and dirty state, never remotes, authors, diffs, or credentials.

    Args:
        root (Path): Identity definition checkout.
        template_revision (str | None): Explicit known upstream template SHA.

    Returns:
        Provenance: Observed Git metadata and installed package version, with unknowns preserved.
    """
    try:
        installed = version("witful")
    except PackageNotFoundError:
        installed = "unknown"
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD^{commit}"], capture_output=True, text=True, timeout=10, check=False
        )
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=normal"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return Provenance(template_revision=template_revision, package_version=installed)
    if head.returncode or status.returncode:
        return Provenance(template_revision=template_revision, package_version=installed)
    return Provenance(head.stdout.strip(), bool(status.stdout.strip()), template_revision, installed)


def _capture(root: Path) -> Evidence:
    """
    Persist a native Life snapshot while retaining native journal heads without rewriting either journal.

    Args:
        root (Path): Existing collection containing native knowledge sources.

    Returns:
        Evidence: Native content references; missing source inputs remain explicit gaps.
    """
    required = ("lessons.jsonl", "knowledge/catalog.json", "knowledge/applications.jsonl")
    if any(not (root / name).exists() for name in required):
        return Evidence(gaps=("native knowledge inputs unavailable",))
    with _owned(root, ".applications.lock").open("a") as applications_lock, _owned(root, ".life.lock").open("a") as life_lock:
        fcntl.flock(applications_lock, fcntl.LOCK_EX)
        fcntl.flock(life_lock, fcntl.LOCK_EX)
        before = tuple((root / name).read_bytes() for name in required)
        snapshot = capture_snapshot(root)
        archive = read_archive(root)
        checkpoints = read_checkpoints(root / "knowledge/checkpoints.jsonl")
        if before != tuple((root / name).read_bytes() for name in required):
            raise RuntimeError("Native sources changed while capturing instance evidence")
        path = _owned(root, f"knowledge/snapshots/{snapshot.id}.json")
        content = canonical(as_data(snapshot)) + b"\n"
        original = path.read_bytes() if path.exists() else None
        if original is not None and original != content:
            raise ValueError("Existing native snapshot cannot be rewritten")
        _durable(path, content, original)
        return Evidence(snapshot.id, archive.events[-1].id if archive.events else None, checkpoints[-1].id if checkpoints else None)


def start(
    root: Path,
    boundary_id: str,
    boundary_kind: Literal["runtime", "logical-session"],
    *,
    session_id: str | None = None,
    served_model: str | None = None,
    model_evidence: str | None = None,
    requested_model: str | None = None,
    template_revision: str | None = None,
    coverage: Literal["incomplete", "complete"] = "incomplete",
    coverage_source: str | None = None,
    parent_instance_id: str | None = None,
    predecessor_instance_id: str | None = None,
) -> Event:
    """
    Reuse an explicit observed boundary or allocate a new UUID and reconcile durable pending tasks.

    Args:
        root (Path): Native collection; starter collections contain no fabricated history.
        boundary_id (str): Stable boundary supplied by the host or explicitly chosen logical session.
        boundary_kind (Literal["runtime", "logical-session"]): What the caller can actually observe.
        session_id (str | None): Optional logical session correlation.
        served_model (str | None): Authoritatively observed served model, never inferred from config.
        model_evidence (str | None): Source supporting served_model, required when it is known.
        requested_model (str | None): Requested configuration kept separate from runtime evidence.
        template_revision (str | None): Known full upstream template commit.
        coverage (Literal["incomplete", "complete"]): Whether relevant external and local task sources were checked.
        coverage_source (str | None): Evidence for a complete reconciliation assertion.
        parent_instance_id (str | None): Existing local parent instance, when known.
        predecessor_instance_id (str | None): Existing local predecessor runtime, when known.

    Returns:
        Event: Existing start event on retry, or newly persisted boundary observation.
    """
    # Capture before creating our own lock file so bookkeeping alone cannot dirty an otherwise clean definition.
    observed_provenance = provenance(root, template_revision)
    with _locked(root) as events:
        catalog = structure(json.loads((root / "knowledge/catalog.json").read_text()), Catalog)
        for event in events:
            item = event.instance
            if item is not None and (item.identity_id, item.boundary_kind, item.boundary_id) == (catalog.id, boundary_kind, boundary_id):
                supplied = (
                    session_id,
                    served_model,
                    model_evidence,
                    requested_model,
                    template_revision,
                    parent_instance_id,
                    predecessor_instance_id,
                )
                stored = (
                    item.session_id,
                    item.served_model,
                    item.model_evidence,
                    item.requested_model,
                    item.provenance.template_revision,
                    item.parent_instance_id,
                    item.predecessor_instance_id,
                )
                if any(value is not None and value != previous for value, previous in zip(supplied, stored, strict=True)):
                    raise ValueError("Boundary metadata conflicts with its existing immutable start")
                return event
        item = Instance(
            str(uuid4()),
            catalog.id,
            boundary_id,
            boundary_kind,
            session_id,
            served_model,
            model_evidence,
            requested_model,
            observed_provenance,
            parent_instance_id,
            predecessor_instance_id,
        )
        event = Event(
            "",
            events[-1].id if events else None,
            datetime.now(UTC).isoformat(),
            item.id,
            "start",
            "start",
            instance=item,
            evidence=_capture(root),
            coverage=coverage,
            coverage_source=coverage_source,
            pending=tuple(item.id for item in pending_tasks(events)),
        )
        return _append(root, events, event)


def require_ready(events: Sequence[Event], instance_id: str) -> None:
    """
    Gate action execution on explicit complete reconciliation for an active known instance.

    Args:
        events (Sequence[Event]): Validated sidecar history.
        instance_id (str): Existing runtime UUID.

    Returns:
        None: The active instance has complete declared reconciliation coverage.
    """
    relevant = [event for event in events if event.instance_id == instance_id]
    if not relevant or relevant[-1].kind == "stop":
        raise ValueError("Unknown or stopped instance")
    reconciliation = next((event for event in reversed(relevant) if event.kind in {"start", "reconcile"}), None)
    if reconciliation is None or reconciliation.coverage != "complete":
        raise ValueError("Action blocked: pending-task reconciliation coverage is incomplete")
    position = next(index for index, event in enumerate(events) if event.id == reconciliation.id)
    if any(event.task is not None and event.instance_id != instance_id for event in events[position + 1 :]):
        raise ValueError("Action blocked: another instance changed the task frontier; reconcile again")


def record(
    root: Path,
    instance_id: str,
    operation_id: str,
    kind: Literal["reconcile", "task", "audit", "observe", "stop"],
    *,
    task: Task | None = None,
    audit: Audit | None = None,
    coverage: Literal["incomplete", "complete"] | None = None,
    coverage_source: str | None = None,
) -> Event:
    """
    Append a lifecycle or task observation with idempotent retry keys and compare-and-set task transitions.

    Args:
        root (Path): Existing collection.
        instance_id (str): Existing UUID, preserved through retries and compaction.
        operation_id (str): Caller-provided stable retry key scoped to this instance.
        kind (Literal["reconcile", "task", "audit", "observe", "stop"]): Explicit event type.
        task (Task | None): Task transition, including its prior event ID when updating.
        audit (Audit | None): Actual action and available request/trace correlation.
        coverage (Literal["incomplete", "complete"] | None): Coverage assertion for reconciliation only.
        coverage_source (str | None): Evidence supporting declared complete coverage.

    Returns:
        Event: Original matching retry event or newly committed observation.
    """
    with _locked(root) as events:
        for event in events:
            if (event.instance_id, event.operation_id) == (instance_id, operation_id):
                if (event.kind, event.task, event.audit, event.coverage, event.coverage_source) != (
                    kind,
                    task,
                    audit,
                    coverage,
                    coverage_source,
                ):
                    raise ValueError("Operation ID was already used for a different request")
                return event
        if kind == "audit" or (task is not None and task.status == "running"):
            require_ready(events, instance_id)
        evidence = _capture(root) if kind == "observe" else None
        event = Event(
            "",
            events[-1].id if events else None,
            datetime.now(UTC).isoformat(),
            instance_id,
            operation_id,
            kind,
            evidence=evidence,
            task=task,
            audit=audit,
            coverage=coverage,
            coverage_source=coverage_source,
            pending=tuple(item.id for item in pending_tasks(events)) if kind == "reconcile" else (),
        )
        return _append(root, events, event)


def instance_resource(root: Path, instance_id: str) -> dict[str, str]:
    """
    Return validated correlation attributes for a connector-supported local audit resource.

    Args:
        root (Path): Collection with a recorded instance UUID.
        instance_id (str): Existing UUID, never a newly fabricated request identifier.

    Returns:
        dict[str, str]: Non-secret resource attributes; unknown model and revision values stay explicit.
    """
    events = read(root)
    require_ready(events, instance_id)
    item = next((event.instance for event in events if event.instance_id == instance_id and event.instance is not None), None)
    if item is None:
        raise ValueError("Unknown instance UUID")
    return resource_attributes(item)


def resource_attributes(item: Instance) -> dict[str, str]:
    """
    Describe validated immutable metadata for historical logs without asserting that a stopped instance is active.

    Args:
        item (Instance): Previously validated start metadata.

    Returns:
        dict[str, str]: Standard and namespaced resource attributes.
    """
    result = {
        "service.name": "witful",
        "witful.instance.id": item.id,
        "witful.identity.id": item.identity_id,
        "witful.instance.boundary.kind": item.boundary_kind,
        "witful.instance.boundary.id": item.boundary_id,
        "witful.definition.revision": item.provenance.revision or "unknown",
        "witful.definition.dirty": str(item.provenance.dirty).lower() if item.provenance.dirty is not None else "unknown",
        "witful.template.revision": item.provenance.template_revision or "unknown",
        "service.version": item.provenance.package_version,
        "gen_ai.response.model": item.served_model or "unknown",
    }
    if item.boundary_kind == "runtime":
        result["service.instance.id"] = item.id
    if item.requested_model is not None:
        result["gen_ai.request.model"] = item.requested_model
    if item.model_evidence is not None:
        result["witful.model.evidence"] = item.model_evidence
    if item.session_id is not None:
        result["witful.session.id"] = item.session_id
    if item.parent_instance_id is not None:
        result["witful.instance.parent.id"] = item.parent_instance_id
    if item.predecessor_instance_id is not None:
        result["witful.instance.predecessor.id"] = item.predecessor_instance_id
    return result


def load_snapshot(root: Path, evidence: Evidence) -> Snapshot | None:
    """
    Resolve a native retained snapshot, leaving absent evidence as an explicit comparison gap.

    Args:
        root (Path): Collection root.
        evidence (Evidence): Validated sidecar reference.

    Returns:
        Snapshot | None: Valid native snapshot, or None when it is absent.
    """
    if evidence.snapshot_id is None:
        return None
    if not _HASH.fullmatch(evidence.snapshot_id):
        raise ValueError("Invalid native snapshot identifier")
    path = _owned(root, f"knowledge/snapshots/{evidence.snapshot_id}.json")
    if not path.exists():
        return None
    item = structure(json.loads(path.read_text()), Snapshot)
    if item.id != evidence.snapshot_id:
        raise ValueError("Native snapshot filename mismatch")
    snapshot_identity(item)
    return item


def check_references(root: Path, events: Sequence[Event]) -> tuple[str, ...]:
    """
    Validate every retained native reference, including superseded observations, and enumerate missing evidence.

    Args:
        root (Path): Native collection root.
        events (Sequence[Event]): Validated instance history.

    Returns:
        tuple[str, ...]: Event-qualified evidence gaps; corrupt existing sources raise instead of becoming zero change.
    """
    archive = read_archive(root)
    life_ids = {event.id for event in archive.events}
    checkpoint_ids = {event.id for event in read_checkpoints(root / "knowledge/checkpoints.jsonl")}
    instances = {event.instance_id: event.instance for event in events if event.instance is not None}
    gaps: list[str] = []
    for event in events:
        if event.evidence is None:
            continue
        evidence = event.evidence
        item = load_snapshot(root, evidence)
        instance = instances[event.instance_id]
        assert instance is not None
        if item is not None and item.catalog.id != instance.identity_id:
            raise ValueError("Native snapshot belongs to a different identity")
        gaps.extend(f"{event.id}: {gap}" for gap in evidence.gaps)
        if item is None:
            gaps.append(f"{event.id}: native knowledge snapshot unavailable")
        if evidence.life_head is not None and evidence.life_head not in life_ids:
            gaps.append(f"{event.id}: native decision head unavailable")
        if evidence.checkpoint_id is not None and evidence.checkpoint_id not in checkpoint_ids:
            gaps.append(f"{event.id}: native checkpoint unavailable")
    return tuple(gaps)
