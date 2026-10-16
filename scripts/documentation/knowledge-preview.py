"""
Render public README examples from invented engineering activity, never a personal collection.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from attrs import evolve
from witful.knowledge.applications import application_id, validate_applications
from witful.knowledge.models import Application, Discipline, Identity, Relation, Skill
from witful.knowledge.plotting import write_plots


def example() -> tuple[Identity, tuple[Application, ...]]:
    """
    Build a fixed synthetic collection illustrating cross-discipline practice.

    Returns:
        tuple[Identity, tuple[Application, ...]]: Example structure and invented observations, with no personal provenance.
    """
    identity = Identity(
        "example:engineering",
        "Synthetic engineering example",
        (
            Discipline("design", "Software design", (Skill("contracts", "API contracts"), Skill("testing", "Testing"))),
            Discipline("delivery", "Delivery", (Skill("review", "Code review"), Skill("releases", "Signed releases"))),
            Discipline("operations", "Operations", (Skill("deploy", "Deployment"), Skill("observe", "Observability"))),
            Discipline("security", "Security", (Skill("custody", "Key custody"), Skill("access", "Access control"))),
            Discipline("communication", "Communication", (Skill("docs", "Documentation"), Skill("visuals", "Visual evidence"))),
        ),
        (
            Relation("contracts", "review", "related", "Synthetic example: review API compatibility."),
            Relation("releases", "custody", "requires", "Synthetic example: signing needs controlled key access."),
            Relation("observe", "visuals", "related", "Synthetic example: explain operational evidence."),
        ),
    )
    # Fixed dates and explicit contexts make recency and reuse reproducible. These
    # are illustration inputs, not measurements of any engineer or repository.
    scenarios = (
        ("design", ("contracts", "testing", "review"), "2026-01-30"),
        ("design", ("contracts", "docs"), "2026-01-29"),
        ("design", ("testing", "observe"), "2026-01-28"),
        ("delivery", ("review", "testing"), "2026-01-27"),
        ("delivery", ("releases", "custody"), "2026-01-26"),
        ("operations", ("deploy", "observe", "access"), "2026-01-20"),
        ("security", ("custody", "access", "review"), "2026-01-10"),
        ("communication", ("docs", "visuals", "observe"), "2026-01-01"),
    )
    applications: list[Application] = []

    for number, (discipline, concepts, day) in enumerate(scenarios):
        event = Application(
            "",
            f"synthetic-task-{number}",
            discipline,
            tuple(sorted(concepts)),
            "unassessed",
            "Invented public illustration; no real task outcome is asserted.",
            f"{day}T12:00:00+00:00",
        )
        applications.append(evolve(event, id=application_id(event)))

    result = tuple(applications)
    validate_applications(identity, result)
    return identity, result


def main() -> int:
    """
    Render the synthetic figures using Witful's unchanged collection renderer.

    Returns:
        int: Zero after all deterministic SVG and PNG previews are written.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".cache/readme-preview"))
    args = parser.parse_args()
    identity, applications = example()

    for path in write_plots(identity, applications, args.output):
        print(path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
