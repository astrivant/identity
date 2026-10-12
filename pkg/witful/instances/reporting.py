"""
Compare retained native evidence across observed instances and export private correlated logs.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import matplotlib as mpl
from attrs import frozen
from matplotlib.figure import Figure

from witful.checkpoints.diff import Change, SkillDiff, compare_states
from witful.checkpoints.snapshot import digest, snapshot
from witful.files import replace_file
from witful.instances.journal import check_references, load_snapshot, read, resource_attributes
from witful.knowledge.compiler import index
from witful.knowledge.contracts import as_data
from witful.knowledge.models import Insight, Lesson, Skill
from witful.knowledge.plotting import save_figure
from witful.life.contracts import current_decisions, snapshot_identity
from witful.life.journal import read_archive
from witful.life.models import Archive

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from witful.instances.models import Event, Evidence, Instance
    from witful.life.models import Snapshot


@frozen
class Comparison:
    """
    Describe recorded evidence changes without attributing them causally to a model or instance.

    Attributes:
        before (str | None): Prior actual instance UUID; None for the first baseline.
        after (str): Target actual instance UUID.
        status (str): Baseline, compared, or gap.
        skills (tuple[SkillDiff, ...]): Native per-skill fact changes when comparison is possible.
        decisions (Change): Native decision-key changes, including explicit retirements.
        gaps (tuple[str, ...]): Missing references that prevent an evidence claim.
        structure (Change): Native skill additions, removals, renames, or parent changes.
        insights (Change): Active native insight additions, removals, and revisions.
        before_observed_at (str | None): Actual prior retained endpoint time, when available.
        after_observed_at (str | None): Actual target retained endpoint time.
        overlap (bool): The previous endpoint was recorded after this instance started.
    """

    before: str | None
    after: str
    status: str
    skills: tuple[SkillDiff, ...] = ()
    decisions: Change = Change()
    gaps: tuple[str, ...] = ()
    structure: Change = Change()
    insights: Change = Change()
    before_observed_at: str | None = None
    after_observed_at: str | None = None
    overlap: bool = False


def _decisions(archive: Archive, evidence: Evidence) -> dict[str, str] | None:
    """
    Project active decisions at the exact retained native journal head.

    Args:
        archive (Archive): Fully validated native decision history.
        evidence (Evidence): Sidecar reference selecting its observed prefix.

    Returns:
        dict[str, str] | None: Decision keys and native event IDs, or None when the head is missing.
    """
    if evidence.life_head is None:
        return {}
    for position, event in enumerate(archive.events):
        if event.id == evidence.life_head:
            prefix = Archive(archive.events[: position + 1], archive.snapshots)
            return {item.decision.key: item.id for item in current_decisions(prefix) if item.decision.status == "accepted"}
    return None


def _change(before: dict[str, str], after: dict[str, str]) -> Change:
    """
    Compare canonical native identifiers and content fingerprints.

    Args:
        before (dict[str, str]): Earlier native keys and digests.
        after (dict[str, str]): Later native keys and digests.

    Returns:
        Change: Exact added, removed, and revised keys.
    """
    return Change(
        tuple(sorted(after.keys() - before.keys())),
        tuple(sorted(before.keys() - after.keys())),
        tuple(sorted(key for key in before.keys() & after.keys() if before[key] != after[key])),
    )


def _structure(item: Snapshot) -> tuple[dict[str, str], dict[str, str]]:
    """
    Project native skill structure and active insight content without fabricating an understanding score.

    Args:
        item (Snapshot): Valid native Life snapshot.

    Returns:
        tuple[dict[str, str], dict[str, str]]: Skill structure and active insight fingerprints by native ID.
    """
    identity = snapshot_identity(item)
    nodes, parents = index(identity)
    superseded = {node.supersedes for node in nodes.values() if isinstance(node, Lesson) and node.supersedes}
    skills = {key: digest([node.name, parents.get(key)]) for key, node in nodes.items() if isinstance(node, Skill)}
    insights = {
        key: digest([as_data(node), parents.get(key)])
        for key, node in nodes.items()
        if isinstance(node, Insight) and parents.get(key) not in superseded
    }
    return skills, insights


def comparisons(root: Path, events: Sequence[Event]) -> tuple[Comparison, ...]:
    """
    Compare each instance endpoint with the previous observed instance of the same native identity.

    Args:
        root (Path): Collection retaining native snapshots and Life journal.
        events (Sequence[Event]): Validated sidecar observations in append order.

    Returns:
        tuple[Comparison, ...]: Baselines, exact changes, and explicit evidence gaps in boundary order.
    """
    instances = [event.instance for event in events if event.instance is not None]
    endpoint_events = {event.instance_id: event for event in events if event.evidence is not None}
    endpoints = {key: event.evidence for key, event in endpoint_events.items()}
    positions = {event.id: position for position, event in enumerate(events)}
    starts = {event.instance_id: event for event in events if event.instance is not None}
    archive = read_archive(root)
    previous: dict[str, Instance] = {}
    result: list[Comparison] = []
    for item in instances:
        prior = previous.get(item.identity_id)
        previous[item.identity_id] = item
        endpoint = endpoint_events[item.id]
        current_evidence = endpoints[item.id]
        assert current_evidence is not None
        current_snapshot = load_snapshot(root, current_evidence)
        if current_snapshot is not None and current_snapshot.catalog.id != item.identity_id:
            raise ValueError("Instance references a snapshot belonging to another identity")
        if prior is None:
            missing = (*current_evidence.gaps, *(("native knowledge snapshot unavailable",) if current_snapshot is None else ()))
            result.append(Comparison(None, item.id, "gap" if missing else "baseline", gaps=missing, after_observed_at=endpoint.recorded_at))
            continue
        prior_endpoint = endpoint_events[prior.id]
        overlap = positions[prior_endpoint.id] > positions[starts[item.id].id]
        left, right = endpoints[prior.id], endpoints[item.id]
        assert left is not None and right is not None
        before, after = load_snapshot(root, left), load_snapshot(root, right)
        left_decisions, right_decisions = _decisions(archive, left), _decisions(archive, right)
        gaps = [*left.gaps, *right.gaps]
        if before is None or after is None:
            gaps.append("native knowledge snapshot unavailable")
        if left_decisions is None or right_decisions is None:
            gaps.append("native decision head unavailable")
        if gaps:
            result.append(
                Comparison(
                    prior.id,
                    item.id,
                    "gap",
                    gaps=tuple(sorted(set(gaps))),
                    before_observed_at=prior_endpoint.recorded_at,
                    after_observed_at=endpoint.recorded_at,
                    overlap=overlap,
                )
            )
            continue
        assert before is not None and after is not None and left_decisions is not None and right_decisions is not None
        if before.catalog.id != item.identity_id or after.catalog.id != item.identity_id:
            raise ValueError("Instance references a snapshot belonging to another identity")
        skills = compare_states(
            snapshot(snapshot_identity(before), before.applications), snapshot(snapshot_identity(after), after.applications)
        )
        decisions = _change(left_decisions, right_decisions)
        before_structure, before_insights = _structure(before)
        after_structure, after_insights = _structure(after)
        result.append(
            Comparison(
                prior.id,
                item.id,
                "compared",
                skills,
                decisions,
                structure=_change(before_structure, after_structure),
                insights=_change(before_insights, after_insights),
                before_observed_at=prior_endpoint.recorded_at,
                after_observed_at=endpoint.recorded_at,
                overlap=overlap,
            )
        )
    return tuple(result)


def _counts(item: Comparison) -> tuple[tuple[int, int, int], ...]:
    """
    Count native per-skill memberships separately from active decision keys.

    Args:
        item (Comparison): Valid evidence comparison.

    Returns:
        tuple[tuple[int, int, int], ...]: Added, removed, and revised counts for skill structure, insights, lessons, uses, and decisions.
    """
    groups = (
        [item.structure],
        [item.insights],
        [skill.lessons for skill in item.skills],
        [skill.uses for skill in item.skills],
        [item.decisions],
    )
    return tuple(
        (
            sum(len(change.added) for change in group),
            sum(len(change.removed) for change in group),
            sum(len(change.revised) for change in group),
        )
        for group in groups
    )


def build(root: Path, destination: Path, limit: int = 8, *, projection: bool = False) -> tuple[Path, ...]:
    """
    Render bounded native evidence comparisons and export all retained instance observations.

    Args:
        root (Path): Collection with optional sidecar history.
        destination (Path): Private artifact output directory.
        limit (int): Maximum visible instances from one through twenty.
        projection (bool): Omit outer heading when a receiving document supplies it.

    Returns:
        tuple[Path, ...]: Complete JSON export and SVG/PNG chart paths.
    """
    if not 1 <= limit <= 20:
        raise ValueError("Instance plot limit must be between one and twenty")
    events = read(root)
    gaps = check_references(root, events)
    differences = comparisons(root, events)
    instances = {event.instance_id: event.instance for event in events if event.instance is not None}
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "instances.json"
    payload = {
        "events": [as_data(event) for event in events],
        "evidence_gaps": list(gaps),
        "comparisons": [as_data(item) for item in differences],
        "semantics": "Native recorded evidence changes, not understanding scores or causal model attribution",
    }
    replace_file(
        path, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(), expected=path.read_bytes() if path.exists() else None
    )
    visible = list(reversed(differences[-limit:]))
    with mpl.rc_context({"svg.hashsalt": "witful-instances", "svg.fonttype": "none"}):
        figure = Figure(figsize=(15, max(4.3, 2.5 + 1.05 * len(visible))), layout="constrained")
        if not projection:
            figure.suptitle(
                "Observed instances\nWhat native knowledge and decisions changed between retained boundaries?",
                fontsize=15,
                gid="plot-heading",
            )
        axis = figure.subplots()
        if not visible:
            axis.text(
                0.5,
                0.5,
                "No instance observations recorded\nThe first observed boundary establishes a baseline",
                transform=axis.transAxes,
                ha="center",
                va="center",
                color="#586774",
            )
            axis.set_axis_off()
        else:
            cells = [[sum(count) for count in _counts(item)] for item in visible]
            maximum = max(max(row) for row in cells)
            axis.imshow(cells, cmap="Blues", vmin=0, vmax=max(2, maximum * 2), aspect="auto")
            axis.set_xticks(range(5), ["Skill structure", "Active insights", "Lesson memberships", "Use memberships", "Active decisions"])
            labels = []
            for row, item in enumerate(visible):
                instance = instances[item.after]
                assert instance is not None
                model = instance.served_model or "served model unknown"
                # Bounded labels keep long provider model names from crushing the chart.
                observed = (
                    datetime.fromisoformat(item.after_observed_at).astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
                    if item.after_observed_at
                    else "time unknown"
                )
                revision = instance.provenance.revision[:7] if instance.provenance.revision else "revision unknown"
                dirty = " dirty" if instance.provenance.dirty else " state unknown" if instance.provenance.dirty is None else ""
                overlap = " · overlapping windows" if item.overlap else ""
                labels.append(
                    f"{item.after[:8]} · {instance.boundary_kind}{overlap}\nendpoint {observed}\n{model[:32]} · start {revision}{dirty}"
                )
                for column, values in enumerate(_counts(item)):
                    text = f"+{values[0]} / -{values[1]} / ~{values[2]}" if item.status == "compared" else item.status
                    axis.text(column, row, text, ha="center", va="center", fontsize=10, color="#193448")
            axis.set_yticks(range(len(visible)), labels, fontsize=9)
            axis.tick_params(length=0)
            axis.set_xlabel(
                "+ added / - removed / ~ revised. Baseline is not new learning; gaps are not zero change.\n"
                "Rows follow start order; endpoints may overlap. Insight edits also revise parent lessons. "
                "Model/revision are startup metadata. Counts do not establish causality.",
                labelpad=14,
            )
        outputs = save_figure(figure, destination, "instance-comparisons", projection=projection)
    return (path, *outputs)


def logs(root: Path) -> dict[str, object]:
    """
    Build a private OTLP/JSON ExportLogsServiceRequest without starting an exporter or inventing trace IDs.

    Args:
        root (Path): Source collection with validated instance observations.

    Returns:
        dict[str, object]: OTLP JSON resourceLogs with string nanoseconds and typed attribute values.
    """
    events = read(root)
    resources: list[dict[str, object]] = []
    for start in (event for event in events if event.instance is not None):
        assert start.instance is not None
        records: list[dict[str, object]] = []
        for event in events:
            if event.instance_id != start.instance_id:
                continue
            timestamp = datetime.fromisoformat(event.recorded_at).astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
            nanos = ((timestamp.days * 86400 + timestamp.seconds) * 1000000 + timestamp.microseconds) * 1000
            attributes = {"witful.event.id": event.id, "witful.event.kind": event.kind, "witful.operation.id": event.operation_id}
            if event.audit is not None:
                attributes.update({"witful.action": event.audit.action, "witful.outcome": event.audit.outcome})
                if event.audit.request_id is not None:
                    attributes["witful.request.id"] = event.audit.request_id
            record: dict[str, object] = {
                "timeUnixNano": str(nanos),
                "observedTimeUnixNano": str(nanos),
                "severityNumber": 9,
                "severityText": "INFO",
                "body": {"stringValue": f"witful.instance.{event.kind}"},
                "attributes": [{"key": key, "value": {"stringValue": value}} for key, value in sorted(attributes.items())],
            }
            if event.audit is not None:
                if event.audit.trace_id is not None:
                    record["traceId"] = event.audit.trace_id
                if event.audit.span_id is not None:
                    record["spanId"] = event.audit.span_id
            records.append(record)
        resources.append(
            {
                "resource": {
                    "attributes": [
                        {"key": key, "value": {"stringValue": value}} for key, value in sorted(resource_attributes(start.instance).items())
                    ]
                },
                "scopeLogs": [{"scope": {"name": "witful.instances"}, "logRecords": records}],
            }
        )
    return {"resourceLogs": resources}
