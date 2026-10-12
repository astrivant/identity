"""
Verify truthful boundaries, native evidence reuse, durable task handoffs, and corruption handling.
"""

from __future__ import annotations

import json
import multiprocessing
import subprocess
from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from attrs import evolve
from witful.collection.archive import pack, unpack
from witful.collection.archive import validate as validate_collection
from witful.instances.cli import main
from witful.instances.journal import instance_resource, pending_tasks, provenance, read, record, require_ready, start, validate
from witful.instances.models import Audit, Task
from witful.instances.reporting import build, comparisons, logs
from witful.knowledge.contracts import as_data
from witful.life.contracts import content_id
from witful.life.journal import read_archive, record_decision
from witful.life.models import Decision

if TYPE_CHECKING:
    from pathlib import Path


def test_boundary_reuse_unknown_model_and_distinct_sessions(collection: Path) -> None:
    """
    Preserve one UUID across wakes and retries without inventing served models from config.

    Args:
        collection (Path): Synthetic native collection.

    Returns:
        None: Stable boundaries, explicit fallback scope, and immutable retry metadata are enforced.
    """
    first = start(collection, "runtime:one", "runtime", session_id="session:one", requested_model="requested-fixture")
    assert UUID(first.instance_id).version == 4
    assert first.instance is not None and first.instance.served_model is None
    assert start(collection, "runtime:one", "runtime") == first
    with pytest.raises(ValueError, match="conflicts"):
        start(collection, "runtime:one", "runtime", requested_model="changed")
    with pytest.raises(ValueError, match="incomplete"):
        instance_resource(collection, first.instance_id)
    record(collection, first.instance_id, "reconcile:1", "reconcile", coverage="complete", coverage_source="fixture:review")
    attrs = instance_resource(collection, first.instance_id)
    assert attrs["service.instance.id"] == first.instance_id
    assert attrs["gen_ai.response.model"] == "unknown"
    assert attrs["gen_ai.request.model"] == "requested-fixture"
    second = start(
        collection,
        "logical:one",
        "logical-session",
        session_id="session:one",
        coverage="complete",
        coverage_source="fixture:review",
        parent_instance_id=first.instance_id,
    )
    assert second.instance_id != first.instance_id
    attrs = instance_resource(collection, second.instance_id)
    assert "service.instance.id" not in attrs
    assert attrs["witful.instance.id"] == second.instance_id
    assert attrs["witful.instance.parent.id"] == first.instance_id


def test_authoritative_model_and_revision_provenance(collection: Path) -> None:
    """
    Require evidence for model claims and retain actual dirty definition state.

    Args:
        collection (Path): Uncommitted synthetic native sources inside Git.

    Returns:
        None: Unknown and dirty states are distinguished from clean commits.
    """
    observed = provenance(collection, "b" * 40)
    assert observed.revision and len(observed.revision) == 40 and observed.dirty is True
    assert observed.template_revision == "b" * 40
    with pytest.raises(ValueError, match="authoritative evidence"):
        start(collection, "invalid:model", "runtime", served_model="fixture-model")
    assert read(collection) == ()
    event = start(collection, "observed:1", "runtime", served_model="fixture-model", model_evidence="runtime:response-metadata")
    assert event.instance is not None and event.instance.served_model == "fixture-model"
    with pytest.raises(ValueError, match="Parent and predecessor"):
        start(collection, "invalid:parent", "runtime", parent_instance_id="00000000-0000-4000-8000-000000000000")


def test_task_reconciliation_compare_and_set_and_retry(collection: Path) -> None:
    """
    Restore unfinished tasks, reject stale updates, and preserve uncertain outcomes as pending work.

    Args:
        collection (Path): Synthetic source collection.

    Returns:
        None: Task handoffs retain exact predecessors and complete coverage gates actual action recording.
    """
    first = start(collection, "runtime:first", "runtime")
    task = Task("task:one", "pending", "Check the synthetic result", "fixture:request")
    pending = record(collection, first.instance_id, "task:pending", "task", task=task)
    assert record(collection, first.instance_id, "task:pending", "task", task=task) == pending
    with pytest.raises(ValueError, match="different request"):
        record(collection, first.instance_id, "task:pending", "task", task=evolve(task, summary="Different"))
    second = start(collection, "runtime:second", "runtime", predecessor_instance_id=first.instance_id)
    assert second.pending == (pending.id,)
    with pytest.raises(ValueError, match="incomplete"):
        record(collection, second.instance_id, "audit:blocked", "audit", audit=Audit("tool.check", "unknown"))
    with pytest.raises(ValueError, match="coverage source"):
        record(collection, second.instance_id, "reconcile:bad", "reconcile", coverage="complete")
    record(collection, second.instance_id, "reconcile:1", "reconcile", coverage="complete", coverage_source="fixture:all-sources-reviewed")
    running = record(collection, second.instance_id, "task:running", "task", task=evolve(task, status="running", previous=pending.id))
    with pytest.raises(ValueError, match="exact previous"):
        record(collection, second.instance_id, "task:stale", "task", task=evolve(task, status="blocked", previous=pending.id))
    assert pending_tasks(read(collection)) == (running,)
    done = record(collection, second.instance_id, "task:done", "task", task=evolve(task, status="succeeded", previous=running.id))
    assert pending_tasks(read(collection)) == ()
    with pytest.raises(ValueError, match="Completed tasks"):
        record(collection, second.instance_id, "task:reopen", "task", task=evolve(task, previous=done.id))
    record(collection, second.instance_id, "stop:1", "stop")
    with pytest.raises(ValueError, match="stopped"):
        instance_resource(collection, second.instance_id)


def test_concurrent_process_start_and_unique_boundaries(collection: Path) -> None:
    """
    Serialize independent writers while allowing distinct observed instances in the same journal.

    Args:
        collection (Path): Shared synthetic collection.

    Returns:
        None: Competing retries reuse one ID and different boundaries retain their own IDs.
    """
    with ProcessPoolExecutor(max_workers=4, mp_context=multiprocessing.get_context("spawn")) as executor:
        same = [item.instance_id for item in executor.map(start, [collection] * 8, ["runtime:shared"] * 8, ["runtime"] * 8)]
        distinct = [
            item.instance_id for item in executor.map(start, [collection] * 4, [f"runtime:{index}" for index in range(4)], ["runtime"] * 4)
        ]
    assert len(set(same)) == 1
    assert len(set(distinct)) == 4
    assert len(read(collection)) == 5


def test_corruption_truncation_and_invalid_metadata_fail_closed(collection: Path) -> None:
    """
    Preserve damaged source bytes rather than manufacturing repaired chronology.

    Args:
        collection (Path): Synthetic source collection.

    Returns:
        None: Invalid source records are rejected before any additional journal append.
    """
    event = start(collection, "runtime:valid", "runtime")
    with pytest.raises(ValueError, match="content or history"):
        validate([evolve(event, operation_id="changed")])
    changed = evolve(event, pending=("a" * 64,))
    changed = evolve(changed, id=content_id(changed))
    with pytest.raises(ValueError, match="pending task frontier"):
        validate([changed])
    path = collection / "knowledge/instances.jsonl"
    path.write_bytes(path.read_bytes()[:-1])
    original = path.read_bytes()
    with pytest.raises(ValueError, match="Truncated"):
        start(collection, "runtime:next", "runtime")
    assert path.read_bytes() == original


def test_archive_round_trip_keeps_sidecar_and_native_snapshots(collection: Path, tmp_path: Path) -> None:
    """
    Seal and restore instance state through the same private collection source allowlist.

    Args:
        collection (Path): Synthetic source collection.
        tmp_path (Path): Isolated restore destination parent.

    Returns:
        None: Native journals remain unchanged and every retained instance reference survives packing.
    """
    original = {
        name: (collection / name).read_bytes() for name in ("lessons.jsonl", "knowledge/catalog.json", "knowledge/applications.jsonl")
    }
    start(collection, "runtime:first", "runtime")
    start(collection, "runtime:second", "runtime")
    restored = tmp_path / "restored"
    unpack(pack(collection), restored)
    validate_collection(restored)
    assert read(restored) == read(collection)
    assert comparisons(restored, read(restored))[1].status == "compared"
    assert read_archive(collection).events == ()
    assert not (collection / "knowledge/life.jsonl").exists()
    assert not (collection / "knowledge/checkpoints.jsonl").exists()
    assert all((collection / name).read_bytes() == content for name, content in original.items())


def test_native_knowledge_and_decision_changes(collection: Path) -> None:
    """
    Compare native stable facts and decision revisions without asserting initial learning.

    Args:
        collection (Path): Collection with one synthetic sourced lesson.

    Returns:
        None: Native revisions, removed decisions, no-change observations, and evidence gaps stay distinct.
    """
    first = start(collection, "runtime:baseline", "runtime")
    decision = Decision(
        "choice:one", "Fixture choice", "Fixture task", "Use the native schema", "Preserve evidence", "fixture:request", ("s",)
    )
    accepted = record_decision(collection, decision)
    second = start(collection, "runtime:after", "runtime")
    diff = comparisons(collection, read(collection))
    assert diff[0].status == "baseline" and diff[0].decisions.added == ()
    assert diff[1].decisions.added == ("choice:one",)
    record_decision(collection, evolve(decision, status="retired", supersedes=accepted.id))
    from dataclasses import asdict

    from witful.lessons import new_lesson

    added = new_lesson("Testing", "Additional synthetic teaching", "fixture:addition", "2026-01-02T00:00:00Z")
    with (collection / "lessons.jsonl").open("a") as stream:
        stream.write(json.dumps(asdict(added)) + "\n")
    third = start(collection, "runtime:retired", "runtime")
    diff = comparisons(collection, read(collection))
    assert diff[2].decisions.removed == ("choice:one",)
    assert diff[2].skills[0].lessons.added == (added.id,)
    assert first.evidence is not None and second.evidence is not None and third.evidence is not None
    target = collection / "knowledge/snapshots" / f"{third.evidence.snapshot_id}.json"
    target.rename(target.with_suffix(".retained"))
    assert comparisons(collection, read(collection))[-1].status == "gap"


def test_build_empty_baseline_and_zero_change(collection: Path, tmp_path: Path) -> None:
    """
    Render empty, baseline, and unchanged evidence honestly and deterministically.

    Args:
        collection (Path): Synthetic native collection.
        tmp_path (Path): Output parent.

    Returns:
        None: No fabricated graph or competency metric is generated.
    """
    destination = tmp_path / "plots"
    files = build(collection, destination)
    assert len(files) == 3
    assert "No instance observations recorded" in (destination / "instance-comparisons.svg").read_text()
    start(collection, "runtime:first", "runtime")
    start(collection, "runtime:second", "runtime")
    files = build(collection, destination)
    original = {path: path.read_bytes() for path in files}
    build(collection, destination)
    assert all(path.read_bytes() == data for path, data in original.items())
    exported = json.loads((destination / "instances.json").read_text())
    assert exported["comparisons"][1]["status"] == "compared"
    assert exported["comparisons"][1]["skills"] == []
    assert "+0 / -0 / ~0" in (destination / "instance-comparisons.svg").read_text()


def test_cli_ready_guard_and_json_contract(collection: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """
    Exercise public CLI startup, reconciliation, and validated resource output.

    Args:
        collection (Path): Synthetic native collection.
        capsys (pytest.CaptureFixture[str]): Captured command output.

    Returns:
        None: CLI callers receive parseable source IDs and explicit incomplete coverage failures.
    """
    args = ["--repo", str(collection)]
    assert main([*args, "start", "--boundary-id", "cli:one", "--boundary-kind", "runtime"]) == 0
    identifier = json.loads(capsys.readouterr().out)["instance_id"]
    with pytest.raises(SystemExit) as failed:
        main([*args, "guard", "--instance-id", identifier])
    assert failed.value.code == 2
    assert (
        main(
            [
                *args,
                "reconcile",
                "--instance-id",
                identifier,
                "--operation-id",
                "review:1",
                "--coverage",
                "complete",
                "--coverage-source",
                "fixture:review",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main([*args, "resource", "--instance-id", identifier]) == 0
    assert json.loads(capsys.readouterr().out)["service.instance.id"] == identifier
    require_ready(read(collection), identifier)


def test_private_log_json_matches_otlp_protobuf_contract(collection: Path) -> None:
    """
    Parse emitted OTLP JSON against the official protobuf message with its specified hex ID conversion.

    Args:
        collection (Path): Synthetic collection with one correlated action.

    Returns:
        None: Every emitted field is recognized and IDs survive an official protobuf round trip.
    """
    import base64

    from google.protobuf.json_format import ParseDict
    from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest

    started = start(collection, "runtime:logs", "runtime", coverage="complete", coverage_source="fixture:review")
    audit = Audit("tool.inspect", "succeeded", "request:fixture", "1" * 32, "2" * 16)
    record(collection, started.instance_id, "action:1", "audit", audit=audit)
    payload = logs(collection)
    # OTLP JSON specifies hex trace/span IDs, unlike generic protobuf JSON bytes' base64 representation.
    normalized = json.loads(json.dumps(payload))
    for resource in normalized["resourceLogs"]:
        for scope in resource["scopeLogs"]:
            for event in scope["logRecords"]:
                for field in ("traceId", "spanId"):
                    if field in event:
                        event[field] = base64.b64encode(bytes.fromhex(event[field])).decode()
    message = ParseDict(normalized, ExportLogsServiceRequest(), ignore_unknown_fields=False)
    decoded = ExportLogsServiceRequest.FromString(message.SerializeToString())
    action = decoded.resource_logs[0].scope_logs[0].log_records[-1]
    assert action.trace_id.hex() == "1" * 32 and action.span_id.hex() == "2" * 16
    assert action.time_unix_nano > 0 and action.severity_number == 9
    assert "task.summary" not in json.dumps(payload)
    assert as_data(started)["instance_id"] == started.instance_id


def test_clean_git_provenance_and_unknown_repository(collection: Path, tmp_path: Path) -> None:
    """
    Keep unknown repository state distinct from a clean synthetic committed definition.

    Args:
        collection (Path): Synthetic Git collection.
        tmp_path (Path): Nonrepository parent.

    Returns:
        None: No fake revision is supplied for missing Git metadata.
    """
    subprocess.run(["git", "-C", str(collection), "add", "lessons.jsonl", "knowledge"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(collection),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "Synthetic source",
        ],
        check=True,
    )
    assert provenance(collection).dirty is False
    assert provenance(tmp_path).revision is None and provenance(tmp_path).dirty is None


def test_other_instance_task_changes_invalidate_readiness(collection: Path) -> None:
    """
    Refuse stale action authorization after another instance changes the durable task frontier.

    Args:
        collection (Path): Synthetic native collection.

    Returns:
        None: A fresh reconciliation is required rather than silently ignoring another writer.
    """
    first = start(collection, "runtime:ready", "runtime", coverage="complete", coverage_source="fixture:review")
    second = start(collection, "runtime:writer", "runtime")
    record(collection, second.instance_id, "task:1", "task", task=Task("task:other", "pending", "Review fixture", "fixture:request"))
    with pytest.raises(ValueError, match="task frontier"):
        instance_resource(collection, first.instance_id)
    reconciled = record(collection, first.instance_id, "review:again", "reconcile", coverage="complete", coverage_source="fixture:review-2")
    assert len(reconciled.pending) == 1
    require_ready(read(collection), first.instance_id)


def test_committed_start_does_not_mark_its_own_new_lock_dirty(collection: Path) -> None:
    """
    Measure definition provenance before first-start bookkeeping modifies an otherwise clean checkout.

    Args:
        collection (Path): Synthetic Git collection.

    Returns:
        None: The first clean definition remains accurately identified as clean at observation.
    """
    subprocess.run(["git", "-C", str(collection), "add", "lessons.jsonl", "knowledge"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(collection),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "Synthetic source",
        ],
        check=True,
    )
    event = start(collection, "runtime:clean", "runtime")
    assert event.instance is not None and event.instance.provenance.dirty is False


def test_lost_acknowledgement_preserves_prefix_and_retry_uuid(collection: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Recover an uncertain append by inspecting durable state rather than duplicating an observed boundary.

    Args:
        collection (Path): Synthetic source collection.
        monkeypatch (pytest.MonkeyPatch): Injected post-publication failure.

    Returns:
        None: A durable event is reused after a caller loses its success acknowledgement.
    """
    from witful.instances import journal

    original = journal._durable
    raised = False

    def uncertain(path: Path, content: bytes, expected: bytes | None) -> None:
        """
        Lose one acknowledgement only after the actual instance file has been durably written.

        Args:
            path (Path): Destination passed by the source writer.
            content (bytes): Complete extended source bytes.
            expected (bytes | None): Exact prior source prefix.

        Returns:
            None: Subsequent writes use the actual durable publication function.
        """
        nonlocal raised
        original(path, content, expected)
        if path.name == "instances.jsonl" and not raised:
            raised = True
            raise RuntimeError("Synthetic acknowledgement loss")

    monkeypatch.setattr(journal, "_durable", uncertain)
    with pytest.raises(RuntimeError, match="acknowledgement"):
        start(collection, "runtime:uncertain", "runtime")
    retained = read(collection)[0]
    assert start(collection, "runtime:uncertain", "runtime") == retained
    prefix = (collection / "knowledge/instances.jsonl").read_bytes()
    start(collection, "runtime:later", "runtime")
    assert (collection / "knowledge/instances.jsonl").read_bytes().startswith(prefix)


def test_redirected_storage_and_payload_like_labels_are_rejected(collection: Path, tmp_path: Path) -> None:
    """
    Refuse metadata payloads and redirected source writes without modifying the external target.

    Args:
        collection (Path): Synthetic source collection.
        tmp_path (Path): External fixture location.

    Returns:
        None: Sidecar writes remain confined and closed metadata fields do not accept arbitrary JSON payloads.
    """
    event = start(collection, "runtime:labels", "runtime", coverage="complete", coverage_source="fixture:review")
    with pytest.raises(ValueError, match="opaque identifier"):
        record(collection, event.instance_id, "action:bad", "audit", audit=Audit('{"raw": "payload"}', "unknown"))
    path = collection / "knowledge/instances.jsonl"
    retained = path.with_suffix(".retained")
    path.rename(retained)
    external = tmp_path / "outside.jsonl"
    external.write_bytes(retained.read_bytes())
    before = external.read_bytes()
    path.symlink_to(external)
    with pytest.raises(ValueError, match="inside its collection"):
        start(collection, "runtime:outside", "runtime")
    assert external.read_bytes() == before


def test_native_insight_and_skill_structure_diffs_and_overlap(collection: Path) -> None:
    """
    Derive structural and insight changes from native IDs while marking concurrent observation windows.

    Args:
        collection (Path): Synthetic collection with one native lesson and skill.

    Returns:
        None: Changes are exact native facts, with overlap retained independently from apparent timestamp order.
    """
    first = start(collection, "runtime:first", "runtime")
    catalog_path = collection / "knowledge/catalog.json"
    catalog = json.loads(catalog_path.read_text())
    lesson = json.loads((collection / "lessons.jsonl").read_text())
    catalog["disciplines"][0]["skills"][0]["name"] = "Renamed schemas"
    catalog["annotations"] = [
        {
            "lesson_id": lesson["id"],
            "name": "Fixture teaching",
            "insights": [
                {"id": "insight:fixture", "name": "Native evidence", "statement": "Preserve native facts", "source": "fixture:annotation"}
            ],
        }
    ]
    catalog_path.write_text(json.dumps(catalog))
    second = start(collection, "runtime:second", "runtime")
    difference = comparisons(collection, read(collection))[-1]
    assert difference.structure.revised == ("s",)
    assert difference.insights.added == ("insight:fixture",)
    assert difference.skills[0].lessons.revised == (lesson["id"],)
    record(collection, first.instance_id, "observe:overlap", "observe")
    difference = comparisons(collection, read(collection))[-1]
    assert difference.overlap is True and difference.before == first.instance_id and difference.after == second.instance_id
    assert difference.before_observed_at and difference.after_observed_at
    assert difference.before_observed_at > difference.after_observed_at


def test_historical_reference_corruption_is_not_hidden_by_later_observation(collection: Path) -> None:
    """
    Check every retained reference even when the chart endpoint has advanced beyond it.

    Args:
        collection (Path): Native synthetic collection.

    Returns:
        None: A modified old snapshot cannot be silently ignored by source validation.
    """
    from dataclasses import asdict

    from witful.instances.journal import check_references
    from witful.lessons import new_lesson

    initial = start(collection, "runtime:history", "runtime")
    added = new_lesson("Testing", "Later fixture", "fixture:add", "2026-01-02T00:00:00Z")
    with (collection / "lessons.jsonl").open("a") as stream:
        stream.write(json.dumps(asdict(added)) + "\n")
    record(collection, initial.instance_id, "observe:later", "observe")
    assert initial.evidence is not None
    target = collection / "knowledge/snapshots" / f"{initial.evidence.snapshot_id}.json"
    data = json.loads(target.read_text())
    data["source_revision"] = "changed"
    target.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="content"):
        check_references(collection, read(collection))
