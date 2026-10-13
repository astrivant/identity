"""
Exercise full-tree coverage, fresh evidence bindings, and native handoff behavior with synthetic collections.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from typing import TYPE_CHECKING

import pytest
from attrs import evolve
from jsonschema import ValidationError
from witful.completion.cli import main
from witful.completion.core import check, plan
from witful.completion.hooks import configuration, handle
from witful.completion.models import Audit, Workspace
from witful.completion.storage import identity, snapshot
from witful.knowledge.contracts import as_data, structure
from witful.knowledge.models import Catalog, Discipline, DisciplineSpec, Identity, Insight, Lesson, Skill, SkillSpec
from witful.lessons import new_lesson

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def tree() -> Identity:
    """
    Build all five levels without personal records or inferred use history.

    Returns:
        Identity: Synthetic tree with one active teaching.
    """
    insight = Insight("insight:one", "One insight", "Check the selected interpreter", "synthetic fixture")
    lesson = Lesson(
        "lesson:one", "One lesson", "Verify runtime selection", "synthetic fixture", "2026-01-01T00:00:00+00:00", insights=(insight,)
    )
    return Identity(
        "identity:example", "Example", (Discipline("discipline:one", "Engineering", (Skill("skill:one", "Runtime", (lesson,)),)),)
    )


def reviewed(audit: Audit) -> Audit:
    """
    Attach explicit synthetic evidence to each active node for tests that require complete coverage.

    Args:
        audit (Audit): Pending synthetic plan.

    Returns:
        Audit: Review containing one independent attestation for every active concept.
    """
    return evolve(
        audit,
        entries=tuple(
            evolve(entry, status="satisfied", reason="Verified the synthetic contract", evidence=("test:contract",))
            if entry.status != "historical"
            else entry
            for entry in audit.entries
        ),
    )


def test_every_level_is_required_and_plan_is_deterministic(tree: Identity) -> None:
    """
    Require every child even when its parent is reviewed, without mutating source data.

    Args:
        tree (Identity): Synthetic complete hierarchy.

    Returns:
        None: Plans are stable and missing Insights fail.
    """
    before = as_data(tree)
    audit = plan(tree, "task", ())
    assert [entry.kind for entry in audit.entries] == ["Identity", "Discipline", "Skill", "Lesson", "Insight"]
    assert plan(tree, "task", ()) == audit
    assert as_data(tree) == before
    assert check(audit, tree, "task", ())
    complete = reviewed(audit)
    assert check(complete, tree, "task", ()) == ()
    assert any(
        "Missing concepts: insight:one" in error for error in check(evolve(complete, entries=complete.entries[:-1]), tree, "task", ())
    )


@pytest.mark.parametrize("change", ["reason", "evidence", "duplicate", "metadata", "unknown", "status"])
def test_incomplete_or_ambiguous_reviews_fail(tree: Identity, change: str) -> None:
    """
    Reject distinct ways a caller could accidentally hide a coverage gap.

    Args:
        tree (Identity): Synthetic complete hierarchy.
        change (str): Independent malformed review case.

    Returns:
        None: Each malformed review has an actionable diagnostic.
    """
    audit = reviewed(plan(tree, "task", ()))
    entry = audit.entries[-1]
    replacements = {
        "reason": evolve(entry, reason=" "),
        "evidence": evolve(entry, evidence=(" ",)),
        "metadata": evolve(entry, parent="identity:example"),
        "unknown": evolve(entry, id="insight:unknown"),
        "status": evolve(entry, status="historical"),
    }
    entries = (*audit.entries, entry) if change == "duplicate" else (*audit.entries[:-1], replacements[change])
    assert check(evolve(audit, entries=entries), tree, "task", ())


def test_source_task_and_workspace_freshness(tree: Identity) -> None:
    """
    Prevent an earlier review from silently applying to another source state or task.

    Args:
        tree (Identity): Synthetic complete hierarchy.

    Returns:
        None: Changed source, task, and workspace bindings all fail.
    """
    workspace = Workspace("/example", "a" * 40, "b" * 64)
    audit = reviewed(plan(tree, "task", (workspace,)))
    assert check(audit, tree, "another-task", (workspace,))
    assert check(audit, evolve(tree, name="Changed"), "task", (workspace,))
    assert check(audit, tree, "task", (evolve(workspace, digest="c" * 64),))
    assert check(audit, tree, "task", ())


def test_exclusions_and_blocked_handoff_are_explicit(tree: Identity) -> None:
    """
    Keep a blocked handoff available without misreporting completed work or excluding applicable descendants.

    Args:
        tree (Identity): Synthetic complete hierarchy.

    Returns:
        None: An explicit incomplete handoff passes coverage while conflicting exclusions fail.
    """
    audit = reviewed(plan(tree, "task", ()))
    entry = evolve(audit.entries[-1], status="blocked", reason="Approval is pending", evidence=(), next_action="Obtain review approval")
    blocked = evolve(audit, entries=(*audit.entries[:-1], entry))
    assert check(blocked, tree, "task", ())
    handoff = evolve(blocked, outcome="handoff", handoff_reason="Required approval remains pending")
    assert check(handoff, tree, "task", ()) == ()
    parent = evolve(audit.entries[0], status="not_applicable", reason="Incorrect exclusion", evidence=())
    assert check(evolve(audit, entries=(parent, *audit.entries[1:])), tree, "task", ())


def test_superseded_teachings_remain_visible(tree: Identity) -> None:
    """
    Exempt only explicitly superseded Lessons and their Insights, retaining history in the tree.

    Args:
        tree (Identity): Synthetic complete hierarchy.

    Returns:
        None: Supersession preserves old nodes and requires the replacement to be reviewed.
    """
    discipline = tree.disciplines[0]
    skill = discipline.skills[0]
    old = skill.lessons[0]
    newer = evolve(old, id="lesson:new", supersedes=old.id, insights=())
    current = evolve(tree, disciplines=(evolve(discipline, skills=(evolve(skill, lessons=(old, newer)),)),))
    audit = plan(current, "task", ())
    assert [entry.id for entry in audit.entries if entry.status == "historical"] == ["lesson:one", "insight:one"]
    assert check(reviewed(audit), current, "task", ()) == ()


def test_closed_schema_round_trip(tree: Identity) -> None:
    """
    Preserve source types and reject unknown fields or unsupported status strings.

    Args:
        tree (Identity): Synthetic complete hierarchy.

    Returns:
        None: Valid input round trips and malformed records fail schema validation.
    """
    audit = plan(tree, "task", ())
    assert structure(as_data(audit), Audit) == audit
    with pytest.raises(ValidationError):
        structure({**as_data(audit), "automatically_approved": True}, Audit)


@pytest.fixture
def collection(tmp_path: Path) -> Path:
    """
    Create an isolated committed collection for filesystem and native hook integration checks.

    Args:
        tmp_path (Path): Pytest-owned temporary directory.

    Returns:
        Path: Synthetic collection with only safe test data and ignored runtime reviews.
    """
    root = tmp_path / "collection"
    (root / "knowledge").mkdir(parents=True)
    record = new_lesson("Runtime", "Verify selection", "synthetic fixture", "2026-01-01T00:00:00+00:00")
    (root / "lessons.jsonl").write_text(json.dumps(asdict(record)) + "\n")
    catalog = Catalog(
        "identity:example",
        "Example",
        2,
        (DisciplineSpec("discipline:one", "Engineering", (SkillSpec("skill:one", "Runtime", ("Runtime",)),)),),
    )
    (root / "knowledge/catalog.json").write_text(json.dumps(as_data(catalog)))
    (root / ".gitignore").write_text(".witful/\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "Synthetic collection",
        ],
        check=True,
    )
    return root


def test_workspace_captures_content_index_and_untracked_files(collection: Path) -> None:
    """
    Detect local changes even when Git index flags hide them from ordinary status output.

    Args:
        collection (Path): Synthetic committed collection.

    Returns:
        None: Worktree bytes, staged state, and new files affect freshness while ignored audits do not.
    """
    before = snapshot(collection)
    path = collection / "lessons.jsonl"
    original = path.read_bytes()
    subprocess.run(["git", "-C", str(collection), "update-index", "--assume-unchanged", "lessons.jsonl"], check=True)
    path.write_bytes(original + b"\n")
    assert snapshot(collection) != before
    path.write_bytes(original)
    assert snapshot(collection) == before
    extra = collection / "new.txt"
    extra.write_text("new work")
    assert snapshot(collection) != before
    extra.unlink()
    runtime = collection / ".witful/completion"
    runtime.mkdir(parents=True)
    (runtime / "example.json").write_text("{}")
    assert snapshot(collection) == before


def test_cli_requires_explicit_review_and_reports_handoff(collection: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """
    Exercise the complete command workflow without claiming pending or blocked work is complete.

    Args:
        collection (Path): Synthetic committed collection.
        capsys (pytest.CaptureFixture[str]): Captured command output.

    Returns:
        None: Pending checks fail, reviewed handoffs pass, and replacing evidence requires explicit selection.
    """
    path = collection / ".witful/completion/test.json"
    base = ["--repo", str(collection)]
    create = [*base, "plan", "--task", "task", "--output", str(path)]
    verify = [*base, "check", "--task", "task", "--input", str(path)]
    assert main(create) == 0
    assert main(create) == 2
    assert main(verify) == 1
    audit = reviewed(structure(json.loads(path.read_text()), Audit))
    path.write_text(json.dumps(as_data(evolve(audit, outcome="handoff", handoff_reason="Awaiting user review"))))
    capsys.readouterr()
    assert main(verify) == 0
    assert json.loads(capsys.readouterr().out)["complete"] is False
    assert main([*create, "--replace"]) == 0
    assert main(verify) == 1


def test_hooks_isolate_sessions_and_honor_exact_deactivation(collection: Path) -> None:
    """
    Keep per-conversation mode and review state independent while persisting no prompt bodies.

    Args:
        collection (Path): Synthetic committed collection.

    Returns:
        None: Only explicit mode commands deactivate this session and Stop rejects missing or stale review.
    """
    payload: dict[str, object] = {
        "session_id": "one",
        "turn_id": "turn",
        "cwd": str(collection),
        "hook_event_name": "UserPromptSubmit",
        "prompt": "Review code",
    }
    assert "hookSpecificOutput" in handle(collection, "example", payload)
    stop = {**payload, "hook_event_name": "Stop"}
    assert handle(collection, "example", stop)["decision"] == "block"
    assert "hookSpecificOutput" in handle(collection, "example", {**payload, "prompt": "Document `identity deactivate`"})
    assert handle(collection, "example", {**payload, "prompt": "identity deactivate"}) == {}
    assert handle(collection, "example", stop) == {}
    assert handle(collection, "example", {**stop, "session_id": "two"})["decision"] == "block"
    assert "hookSpecificOutput" in handle(collection, "example", {**payload, "prompt": "identity activate example"})
    assert all("Review code" not in path.read_text() for path in (collection / ".witful/completion").rglob("*.json"))
    config = configuration(collection, "example")
    assert "UserPromptSubmit" in str(config) and "Stop" in str(config)


def test_stop_checks_the_actual_review_and_current_workspace(collection: Path) -> None:
    """
    Permit a fully reviewed native turn and fail closed when its work changes afterward.

    Args:
        collection (Path): Synthetic committed collection.

    Returns:
        None: The synchronous Stop gate independently refreshes the expected source and workspace.
    """
    payload: dict[str, object] = {
        "session_id": "session",
        "turn_id": "turn",
        "cwd": str(collection),
        "hook_event_name": "UserPromptSubmit",
        "prompt": "Review",
    }
    handle(collection, "example", payload)
    state_path = next((collection / ".witful/completion").rglob("session.json"))
    task = json.loads(state_path.read_text())["task"]
    audit = reviewed(plan(identity(collection), task, (snapshot(collection),)))
    (state_path.parent / f"{task}.json").write_text(json.dumps(as_data(audit)))
    stop = {**payload, "hook_event_name": "Stop", "stop_hook_active": True}
    assert handle(collection, "example", stop) == {}
    (collection / "changed.txt").write_text("new work")
    assert handle(collection, "example", stop)["decision"] == "block"


def test_non_code_prompt_uses_collection_evidence(collection: Path, tmp_path: Path) -> None:
    """
    Support conversational work outside a Git checkout without scanning unrelated files.

    Args:
        collection (Path): Synthetic committed collection.
        tmp_path (Path): Non-Git working directory owned by this test.

    Returns:
        None: The hook supplies a usable plan command requiring only the selected collection snapshot.
    """
    payload: dict[str, object] = {
        "session_id": "non-code",
        "turn_id": "turn",
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
        "prompt": "Explain the concept",
    }
    response = handle(collection, "example", payload)
    assert "hookSpecificOutput" in response
    assert "--workspace" not in str(response)


def test_runtime_state_cannot_escape_through_symlinks(collection: Path, tmp_path: Path) -> None:
    """
    Prevent trusted adapter writes from being redirected through a substituted runtime directory.

    Args:
        collection (Path): Synthetic committed collection.
        tmp_path (Path): Test-owned path outside the collection.

    Returns:
        None: Symlinked runtime paths are rejected before any state write.
    """
    (collection / ".witful").symlink_to(tmp_path, target_is_directory=True)
    payload: dict[str, object] = {
        "session_id": "one",
        "turn_id": "turn",
        "cwd": str(collection),
        "hook_event_name": "UserPromptSubmit",
        "prompt": "Review",
    }
    with pytest.raises(ValueError, match="symlinks"):
        handle(collection, "example", payload)
    assert not (tmp_path / "completion").exists()
