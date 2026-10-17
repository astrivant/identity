"""
Build an explicitly synthetic Life archive and render its bounded decision paths.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from attrs import evolve
from witful.knowledge.models import Catalog, DisciplineSpec, SkillSpec
from witful.lessons import new_lesson
from witful.life.contracts import content_id
from witful.life.journal import renderer_fingerprint
from witful.life.models import Archive, Decision, Event, Snapshot
from witful.life.replay import render


def example(root: Path) -> Archive:
    """
    Create diverse revision paths without reading any user's records.

    Args:
        root (Path): Public checkout used only for the renderer fingerprint.

    Returns:
        Archive: Invented tasks, choices and alternatives with valid content hashes.
    """
    lesson = new_lesson("Design", "Retain reviewed evidence", "Synthetic example", "2026-01-01T00:00:00Z")
    catalog = Catalog(
        "example", "Synthetic collection", disciplines=(DisciplineSpec("design", "Design", (SkillSpec("audit", "Audit", ("Design",)),)),)
    )
    snapshot = Snapshot("", json.dumps(asdict(lesson)) + "\n", catalog, (), renderer_fingerprint(root))
    snapshot = evolve(snapshot, id=content_id(snapshot))
    events: list[Event] = []
    heads: dict[str, str] = {}

    def append(key: str, title: str, choice: str, *, retired: bool = False, alternatives: tuple[str, ...] = ()) -> None:
        """
        Append one synthetic revision, retaining the complete causal journal.

        Args:
            key (str): Stable subject.
            title (str): Compact row label.
            choice (str): Documented chosen action.
            retired (bool): Explicit withdrawal of an existing choice.
            alternatives (tuple[str, ...]): Invented options, never measured outcomes.

        Returns:
            None: Appends an immutable event and advances only its subject head.
        """
        decision = Decision(
            key,
            title,
            "example:review",
            choice,
            "Synthetic demonstration",
            "Synthetic example",
            ("audit",),
            alternatives,
            heads.get(key),
            "retired" if retired else "accepted",
        )
        event = Event("", events[-1].id if events else None, "2026-01-01T00:00:00+00:00", snapshot.id, decision)
        event = evolve(event, id=content_id(event))
        heads[key] = event.id
        events.append(event)

    # Older independent choices exercise subject consolidation without fabricating relationships.
    for name in ("Dependencies", "Onboarding", "Metrics", "Storage"):
        append(name.lower(), name, "Retain the reviewed project default")
    for revision in range(7):
        append("retention", "Record retention", f"Keep generation {revision + 1} under the reviewed retention policy")
    append("release", "Release verification", "Verify artifacts before publication", alternatives=("Verify after publication",))
    append("cache", "Cache strategy", "Cache responses locally", alternatives=("Request every response",))
    append("cache", "Cache strategy", "Retire the cache after invalidation failures", retired=True)
    append("review", "Review ownership", "Ask the component owner", alternatives=("Assign automatically", "Ask the team"))
    append("review", "Review ownership", "Route through the documented ownership map")
    append("rollout", "Rollout policy", "Use a single rollout batch")
    append("rollout", "Rollout policy", "Withdraw the batch policy pending evidence", retired=True)
    append("rollout", "Rollout policy", "Reinstate with measured canary verification", alternatives=("Keep rollout paused",))
    return Archive(tuple(events), (snapshot,))


def main() -> int:
    """
    Render only the invented archive, labeling the review artifact as synthetic.

    Returns:
        int: Zero after PNG, SVG and full JSON history are written.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".cache/life-example"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    for path in render(example(root), root, args.output):
        print(path)
    report = args.output / "life.json"
    data = json.loads(report.read_text())
    data["synthetic"] = True
    report.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
