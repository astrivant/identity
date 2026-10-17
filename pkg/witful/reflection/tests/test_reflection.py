"""
Exercise deterministic review cadence, immutable context, evidence validation, and private transport.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

import pytest
from attrs import evolve
from jsonschema import ValidationError
from witful.collection.archive import allowed, pack, unpack, validate
from witful.knowledge.contracts import as_data, structure
from witful.life.journal import record_decision
from witful.life.models import Decision
from witful.project import main as initialize
from witful.reflection.cli import main
from witful.reflection.journal import read, record, validate_assessments
from witful.reflection.models import Assessment
from witful.reflection.planning import plan
from witful.reflection.plotting import build

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


def git(root: Path, *arguments: str) -> str:
    """
    Run only local synthetic Git commands with signing and hooks disabled for fixtures.

    Args:
        root (Path): Test-owned repository directory.
        *arguments (str): Literal fixture command arguments.

    Returns:
        str: Captured stripped stdout.
    """
    return subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.org",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            *arguments,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()


@pytest.fixture
def collection(tmp_path: Path) -> tuple[Path, Assessment]:
    """
    Create a synthetic decision and local commit history without reading personal data.

    Args:
        tmp_path (Path): Pytest-owned scratch directory.

    Returns:
        tuple[Path, Assessment]: Collection and its first review input.
    """
    root = tmp_path / "collection"
    initialize([str(root)])
    event = record_decision(
        root, Decision("fixture:choice", "Retain evidence", "fixed task", "Append", "Preserve context", "Fixture", ("identity:local",))
    )
    git(root, "init", "--quiet")
    git(root, "add", ".")
    git(root, "commit", "-qm", "Fixture baseline")
    item = Assessment(event.id, "Append", "Current knowledge still supports retained evidence", ("identity:local",), 2, 1, "Fixture check")
    return root, item


def test_review_boundary_and_retry_preserve_decisions(collection: tuple[Path, Assessment], monkeypatch: MonkeyPatch) -> None:
    """
    Cross the default 100-commit boundary without creating an expensive artificial repository history.

    Args:
        collection (tuple[Path, Assessment]): Synthetic decision and collection.
        monkeypatch (MonkeyPatch): Deterministic history length at the Git adapter boundary.

    Returns:
        None: Exactly 100 commits makes a review due; recording is idempotent and preserves original journals.
    """
    from witful.reflection import planning

    root, item = collection
    original = (root / "knowledge/life.jsonl").read_bytes()
    head = git(root, "rev-parse", "HEAD")
    actual = planning._git
    count = 99

    def history(path: Path, *args: str) -> str:
        """
        Vary only the already-resolved first-parent history length.

        Args:
            path (Path): Test repository.
            *args (str): Metadata query.

        Returns:
            str: Stable history or the real Git result.
        """
        if args[0] == "rev-list":
            return "\n".join([head, *(f"{number:040x}" for number in range(1, count))])
        return actual(path, *args)

    monkeypatch.setattr(planning, "_git", history)
    assert plan(root, root)["due"] is False
    count = 100
    assert plan(root, root)["due"] is True
    first = record(root, root, (item,))
    assert record(root, root, (item,)) == first
    assert len(read(root)) == 1
    assert plan(root, root)["due"] is False
    assert (root / "knowledge/life.jsonl").read_bytes() == original


def test_new_knowledge_is_snapshotted_and_old_reviews_remain(collection: tuple[Path, Assessment]) -> None:
    """
    Keep old assessments reproducible after the collection's current knowledge changes.

    Args:
        collection (tuple[Path, Assessment]): Synthetic source and initial assessment.

    Returns:
        None: Separate snapshots retain the previous and current source states.
    """
    root, item = collection
    first = record(root, root, (item,))
    catalog = root / "knowledge/catalog.json"
    content = json.loads(catalog.read_text())
    content["name"] = "Revised fixture knowledge"
    catalog.write_text(json.dumps(content))
    git(root, "add", "knowledge/catalog.json")
    git(root, "commit", "-qm", "Change fixture context")
    second = record(root, root, (evolve(item, current_support=-1, current_choice="Reconsider", rationale="Changed evidence"),))
    assert second.previous == first.id
    assert second.snapshot.id != first.snapshot.id
    assert read(root)[0].snapshot.catalog.name == "Knowledge collection"
    assert second.snapshot.catalog.name == "Revised fixture knowledge"


@pytest.mark.parametrize(
    "changes",
    [
        {"observed_outcome": 3},
        {"observed_outcome": 1, "outcome_evidence": ""},
        {"context_effect": -1},
        {"current_support": 2, "knowledge_ids": ()},
        {"current_support": True},
    ],
)
def test_ratings_require_evidence(collection: tuple[Path, Assessment], changes: dict[str, object]) -> None:
    """
    Reject unsupported ratings rather than inventing reassuring points on a chart.

    Args:
        collection (tuple[Path, Assessment]): Synthetic reviewed input.
        changes (dict[str, object]): One invalid field combination.

    Returns:
        None: Invalid evidence and scores are rejected at the source boundary.
    """
    _, item = collection
    with pytest.raises((ValueError, ValidationError)):
        modified = structure({**as_data(item), **changes}, Assessment)
        validate_assessments((modified,), {item.decision_id}, {"identity:local"})


def test_rotating_batches_and_foreign_history_fail_closed(collection: tuple[Path, Assessment]) -> None:
    """
    Prioritize unreviewed decisions and refuse a rewritten cadence anchor.

    Args:
        collection (tuple[Path, Assessment]): Synthetic repository and assessment.

    Returns:
        None: Bounded rounds rotate and divergent history requires reconciliation.
    """
    root, item = collection
    record(root, root, (item,))
    other = record_decision(
        root, Decision("fixture:other", "Second choice", "other task", "Inspect", "Check inputs", "Fixture", ("identity:local",))
    )
    (root / "knowledge/reflection.json").write_text(json.dumps({"batch_size": 1}))
    assert plan(root, root)["decision_ids"] == [other.id]
    git(root, "checkout", "--orphan", "unrelated")
    git(root, "commit", "-qm", "Different history")
    with pytest.raises(ValueError, match="missing or divergent"):
        plan(root, root)


def test_tampering_and_incomplete_batch_are_rejected(collection: tuple[Path, Assessment]) -> None:
    """
    Refuse incomplete acknowledgments and detect altered review journals.

    Args:
        collection (tuple[Path, Assessment]): Test-owned review sources.

    Returns:
        None: No review is recorded until the full batch validates; changed bytes break its hash.
    """
    root, item = collection
    with pytest.raises(ValueError):
        record(root, root, ())
    record(root, root, (item,))
    path = root / "knowledge/reflections.jsonl"
    path.write_text(path.read_text().replace('"current_support":2', '"current_support":-2'))
    with pytest.raises(ValueError, match="hash chain"):
        read(root)


def test_archive_and_plots_preserve_unknowns_and_replay(collection: tuple[Path, Assessment], tmp_path: Path) -> None:
    """
    Transport reviews through the encrypted source allowlist and generate stable, honest plots.

    Args:
        collection (tuple[Path, Assessment]): Synthetic source and rating.
        tmp_path (Path): Output and recovery paths.

    Returns:
        None: Reviews restore intact and unknown values never become neutral observations.
    """
    root, item = collection
    record(root, root, (item,))
    unpack(pack(root), tmp_path / "restored")
    validate(tmp_path / "restored")
    assert read(root) == read(tmp_path / "restored")
    assert allowed("reflection-plan.json", figures=True)
    assessments = (item, evolve(item, decision_id="unknown", current_support=None, observed_outcome=None))
    output = tmp_path / "plots"
    paths = build(assessments, output)
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
    build(assessments, output)
    assert before == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
    assert "1 unknown/unscored" in (output / "decision-outcomes.svg").read_text()
    assert "2 unknown/unscored" in (output / "decision-context.svg").read_text()


def test_disabled_and_empty_cli_outputs(collection: tuple[Path, Assessment], tmp_path: Path) -> None:
    """
    Keep disabling explicit and render an honest empty state without requiring model credentials.

    Args:
        collection (tuple[Path, Assessment]): Synthetic input set.
        tmp_path (Path): Separate generated destination.

    Returns:
        None: Empty plots render; disabled review generation writes no figure.
    """
    root, _ = collection
    assert main(["--repo", str(root), "build", "--output-dir", str(tmp_path / "empty")]) == 0
    assert "No scored observations" in (tmp_path / "empty/decision-outcomes.svg").read_text()
    (root / "knowledge/reflection.json").write_text('{"enabled":false}')
    assert plan(root, root)["due"] is False
    assert main(["--repo", str(root), "build", "--output-dir", str(tmp_path / "disabled")]) == 0
    assert not (tmp_path / "disabled").exists()


def test_nonempty_partial_batch_and_shallow_history_fail(collection: tuple[Path, Assessment], monkeypatch: MonkeyPatch) -> None:
    """
    Reject partial acknowledgement and truncated history before changing the review journal.

    Args:
        collection (tuple[Path, Assessment]): Synthetic collection with one initial choice.
        monkeypatch (MonkeyPatch): Controlled shallow-history boundary.

    Returns:
        None: Invalid reviews leave no journal, and shallow history cannot schedule a review.
    """
    from witful.reflection import planning

    root, item = collection
    record_decision(root, Decision("fixture:second", "Another choice", "task", "Check", "Evidence", "Fixture", ("identity:local",)))
    with pytest.raises(ValueError, match="every requested decision"):
        record(root, root, (item,))
    assert not (root / "knowledge/reflections.jsonl").exists()
    monkeypatch.setattr(planning, "_git", lambda path, *args: "true")
    with pytest.raises(ValueError, match="full Git history"):
        plan(root, root)


def test_cli_records_a_review_without_accepting_its_lesson(collection: tuple[Path, Assessment], tmp_path: Path) -> None:
    """
    Round-trip an explicit assessment through the command boundary without promoting a proposal.

    Args:
        collection (tuple[Path, Assessment]): Synthetic source and review.
        tmp_path (Path): Private review input destination.

    Returns:
        None: A validated review persists while the authoritative lesson journal stays unchanged.
    """
    root, item = collection
    original = (root / "lessons.jsonl").read_bytes()
    incoming = tmp_path / "assessments.json"
    incoming.write_text(json.dumps([as_data(evolve(item, proposed_lessons=("Investigate before generalizing",)))]))
    assert main(["--repo", str(root), "record", "--input", str(incoming)]) == 0
    assert main(["--repo", str(root), "check"]) == 0
    assert len(read(root)) == 1
    assert (root / "lessons.jsonl").read_bytes() == original
