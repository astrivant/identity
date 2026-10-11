"""
Schedule bounded retrospective batches from Git ancestry and recorded review history.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from witful.knowledge.contracts import as_data
from witful.life.journal import read_archive
from witful.reflection.journal import config, read

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["plan", "revision"]


def _git(root: Path, *arguments: str) -> str:
    """
    Query bounded Git metadata without exposing provider or local diagnostic bodies.

    Args:
        root (Path): Existing repository owning the cadence history.
        *arguments (str): Fixed Git command and literal values.

    Returns:
        str: Successful stripped stdout.

    Raises:
        ValueError: History is missing, divergent, or unavailable.
    """
    try:
        result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("Reflection needs accessible Git history") from None
    if result.returncode:
        raise ValueError("Reflection history is missing or divergent; preserve its review anchor and fetch full history")
    return result.stdout.strip()


def revision(root: Path) -> str:
    """
    Resolve a complete checkout's current commit before computing review cadence.

    Args:
        root (Path): Existing history checkout.

    Returns:
        str: Full commit hash.

    Raises:
        ValueError: A shallow checkout cannot support reliable commit counting.
    """
    if _git(root, "rev-parse", "--is-shallow-repository") == "true":
        raise ValueError("Reflection needs full Git history; fetch-depth must be zero")
    return _git(root, "rev-parse", "--verify", "HEAD^{commit}")


def plan(root: Path, history: Path) -> dict[str, object]:
    """
    Prepare evidence for a human or agent review without generating or scoring any outcome.

    Args:
        root (Path): Source collection with original Life decisions and optional reviews.
        history (Path): Complete Git checkout used for first-parent commit cadence.

    Returns:
        dict[str, object]: Due status and bounded oldest-reviewed-first batch, including original context and revision peers.

    Raises:
        ValueError: The review anchor is not on the current first-parent history.
    """
    settings = config(root)
    if not settings.enabled:
        return {"enabled": False, "due": False, "decision_ids": [], "decisions": [], "decision_count": 0}
    current = revision(history)
    rounds = read(root)
    anchor = rounds[-1].revision if rounds else None
    commits = _git(history, "rev-list", "--first-parent", current).splitlines()
    if anchor is not None and anchor not in commits:
        raise ValueError("The previous review anchor is not on this first-parent history; reconcile before reviewing")
    elapsed = commits.index(anchor) if anchor else len(commits)
    archive = read_archive(root)
    positions = {event.id: number for number, event in enumerate(archive.events)}
    last_review = {item.decision_id: number for number, event in enumerate(rounds) for item in event.assessments}

    # Rotate through older unreviewed subjects before revisiting recent ones; no expensive model call is implicit.
    selected = sorted(archive.events, key=lambda event: (last_review.get(event.id, -1), -positions[event.id]))[: settings.batch_size]
    return {
        "enabled": True,
        "due": bool(selected) and elapsed >= settings.interval_commits,
        "revision": current,
        "previous_review_revision": anchor,
        "commits_since_review": elapsed,
        "interval_commits": settings.interval_commits,
        "decision_ids": sorted(event.id for event in selected),
        "decision_count": len(selected),
        "decisions": [
            {
                "event": as_data(event),
                "original_snapshot_id": event.snapshot_id,
                "same_subject_history": [peer.id for peer in archive.events if peer.decision.key == event.decision.key],
            }
            for event in selected
        ],
        "review_contract": "Apply current knowledge to each original task and constraints. Record later context separately. "
        "Score only supported observations; alternative outcomes are unknown. Lessons remain proposals until reviewed.",
    }
