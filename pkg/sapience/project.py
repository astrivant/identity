"""
Initialize an empty user-owned knowledge collection without personal example data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING

from sapience.knowledge.contracts import as_data, schema
from sapience.knowledge.models import Application, Catalog
from sapience.life.models import Decision, Event, Snapshot

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """
    Create the minimum validated collection without overwriting existing content.

    Args:
        argv (Sequence[str] | None): Explicit arguments or process arguments.

    Returns:
        int: Zero on success; parser exit two for an occupied destination.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)

    if args.path.exists():
        parser.error("Choose a new directory; existing collections are never overwritten")

    root: Path = args.path
    (root / "knowledge/schemas").mkdir(parents=True, mode=0o700)
    (root / "lessons.jsonl").touch(mode=0o600)
    (root / "knowledge/applications.jsonl").touch(mode=0o600)
    (root / "knowledge/life.jsonl").touch(mode=0o600)
    (root / "knowledge/catalog.json").write_text(json.dumps(as_data(Catalog("identity:local", "Knowledge collection")), indent=2) + "\n")
    (root / ".gitignore").write_text(".sapience/\n*.sqlite*\n.*.lock\n")

    for name, model in (
        ("catalog", Catalog),
        ("application", Application),
        ("life-decision", Decision),
        ("life-event", Event),
        ("life-snapshot", Snapshot),
    ):
        (root / f"knowledge/schemas/{name}.schema.json").write_text(json.dumps(schema(model), indent=2, sort_keys=True) + "\n")

    print(f"Initialized {root}; add sourced lessons, curate the catalog, then run sapience --repo {root} build.")
    return 0
