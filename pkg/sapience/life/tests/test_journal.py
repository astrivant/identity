"""
Check append-only decision history, explicit revisions, schema closure, and integrity failures.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest
from attrs import evolve
from jsonschema import ValidationError
from sapience.knowledge.contracts import as_data, structure
from sapience.life.cli import main
from sapience.life.contracts import canonical, content_id, current_decisions, validate_archive
from sapience.life.journal import read_archive, record_decision
from sapience.life.models import Archive, Decision
from sapience.life.replay import prefix

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import CaptureFixture


def test_revisions_retirements_and_retry_idempotence(source: Path, decision: Decision) -> None:
    """
    Retain every revision while repeated requests preserve the original event and timestamp.

    Args:
        source (Path): Synthetic input source.
        decision (Decision): Initial reviewed choice.

    Returns:
        None: Revisions require current-head references and never rewrite earlier journal bytes.
    """
    first = record_decision(source, decision)
    initial = (source / "knowledge/life.jsonl").read_bytes()
    assert record_decision(source, decision) == first
    assert (source / "knowledge/life.jsonl").read_bytes() == initial

    with pytest.raises(ValueError, match="supersede"):
        record_decision(source, evolve(decision, choice="Replace history"))

    second = record_decision(source, evolve(decision, choice="Append with snapshots", supersedes=first.id))
    third = record_decision(source, evolve(second.decision, status="retired", supersedes=second.id, rationale="Scope ended"))
    archive = read_archive(source)
    assert len(archive.events) == 3
    assert len(archive.snapshots) == 1
    assert (source / "knowledge/life.jsonl").read_bytes().startswith(initial)
    assert current_decisions(archive) == (third,)
    assert current_decisions(prefix(archive, first.id)) == (first,)
    assert current_decisions(prefix(archive, second.id)) == (second,)
    assert archive.snapshots[0].applications == ()


@pytest.mark.parametrize("fault", ["rationale", "timestamp", "chain", "unknown-concept", "snapshot", "revision"])
def test_invalid_events_are_rejected(source: Path, decision: Decision, fault: str) -> None:
    """
    Reject altered content and semantically invalid events even after recalculating their digest.

    Args:
        source (Path): Valid synthetic source set.
        decision (Decision): Baseline choice.
        fault (str): Broken invariant to exercise.

    Returns:
        None: No malformed archive reaches rendering or remote storage.
    """
    event = record_decision(source, decision)
    archive = read_archive(source)

    if fault == "rationale":
        changed = evolve(event, decision=evolve(decision, rationale=""))
    elif fault == "timestamp":
        changed = evolve(event, recorded_at="2026-01-01")
    elif fault == "chain":
        changed = evolve(event, previous="missing")
    elif fault == "unknown-concept":
        changed = evolve(event, decision=evolve(decision, concept_ids=("unknown",)))
    elif fault == "snapshot":
        changed = evolve(event, snapshot_id="missing")
    else:
        changed = evolve(event, decision=evolve(decision, supersedes="missing"))

    changed = evolve(changed, id=content_id(changed))

    with pytest.raises(ValueError):
        validate_archive(Archive((changed,), archive.snapshots))


def test_snapshot_tampering_and_path_traversal_fail(source: Path, decision: Decision) -> None:
    """
    Refuse edited replay sources and imported snapshot identifiers that could escape their directory.

    Args:
        source (Path): Valid source set.
        decision (Decision): Choice used to create a snapshot.

    Returns:
        None: The loader validates both content addresses and safe path components.
    """
    event = record_decision(source, decision)
    snapshot = source / "knowledge/snapshots" / f"{event.snapshot_id}.json"
    data = json.loads(snapshot.read_text())
    data["lessons_jsonl"] = ""
    snapshot.write_bytes(canonical(data))

    with pytest.raises(ValueError, match="Snapshot content"):
        read_archive(source)

    altered = evolve(event, snapshot_id="../../config.toml")
    (source / "knowledge/life.jsonl").write_bytes(canonical(as_data(altered)) + b"\n")

    with pytest.raises(ValueError, match="Invalid snapshot identifier"):
        read_archive(source)


def test_concurrent_retries_append_once(source: Path, decision: Decision) -> None:
    """
    Serialize concurrent journal requests without sleep-based timing assumptions.

    Args:
        source (Path): Shared synthetic checkout.
        decision (Decision): Identical reviewed request from four workers.

    Returns:
        None: The stored hash chain contains exactly one event and no duplicate observations.
    """
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: record_decision(source, decision), range(4)))

    assert len({event.id for event in results}) == 1
    assert len(read_archive(source).events) == 1


def test_cli_and_closed_schema(source: Path, decision: Decision, capsys: CaptureFixture[str]) -> None:
    """
    Validate generated schemas and exercise recording, inspection, and invalid input at the command boundary.

    Args:
        source (Path): Synthetic checkout.
        decision (Decision): Reviewed draft.
        capsys (CaptureFixture[str]): Captured CLI output.

    Returns:
        None: CLI records referenceable events and malformed source JSON fails before mutation.
    """
    draft = source / "draft.json"
    draft.write_text(json.dumps(as_data(decision)))
    assert main(["--repo", str(source), "schemas"]) == 0
    assert main(["--repo", str(source), "record", "--input", str(draft)]) == 0
    identifier = capsys.readouterr().out.strip()
    assert main(["--repo", str(source), "show", "--key", decision.key]) == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == identifier
    assert main(["--repo", str(source), "check"]) == 0

    with pytest.raises(ValidationError):
        structure({**as_data(decision), "unexpected": True}, Decision)

    (source / "knowledge/schemas/life-event.schema.json").write_text("{}")

    with pytest.raises(SystemExit) as error:
        main(["--repo", str(source), "check"])

    assert error.value.code == 2
