"""
Render selected figure families from validated collection sources into a portable bundle.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from witful.awareness.models import FIGURES, MAX_BUNDLE_BYTES, MAX_IMAGE_BYTES, Bundle, Figure
from witful.checkpoints.journal import read as read_checkpoints
from witful.checkpoints.plotting import build as checkpoint_plots
from witful.knowledge.applications import read_applications
from witful.knowledge.compiler import compile_identity, index
from witful.knowledge.contracts import as_data, structure
from witful.knowledge.models import Catalog
from witful.knowledge.plotting import write_plots as knowledge_plots
from witful.lessons import read_journal
from witful.life.journal import read_archive
from witful.life.plotting import write_influences
from witful.privacy.scanner import scan_text
from witful.repertoire.journal import validate
from witful.repertoire.models import Inventory, Use
from witful.repertoire.plotting import write_plots as repertoire_plots


def render(root: Path, selected: tuple[str, ...]) -> bytes:
    """
    Rebuild requested views and package only their PNGs after checking visible SVG labels.

    Args:
        root (Path): Existing collection checkout.
        selected (tuple[str, ...]): Unique, nonempty catalog keys in desired order.

    Returns:
        bytes: Canonical JSON bundle bounded for GitHub transport.

    Raises:
        ValueError: Selection, image limits, or detected personal-data patterns prevent publication.
    """
    if not selected or len(set(selected)) != len(selected) or any(key not in FIGURES for key in selected):
        raise ValueError("Select one or more unique awareness figure IDs; all are disabled by default")

    # Temporary render outputs include richer exports; only allowlisted PNG files leave this directory.
    with TemporaryDirectory(prefix="witful-awareness-") as temporary:
        destination = Path(temporary)
        groups = {FIGURES[key][0] for key in selected}

        if groups & {"knowledge", "repertoire"}:
            catalog = structure(json.loads((root / "knowledge/catalog.json").read_text()), Catalog)
            identity = compile_identity(read_journal(root / "lessons.jsonl"), catalog)

            if "knowledge" in groups:
                knowledge_plots(identity, read_applications(root / "knowledge/applications.jsonl"), destination)

            if "repertoire" in groups:
                inventory_path = root / "knowledge/repertoire.json"
                inventory = structure(json.loads(inventory_path.read_text()), Inventory) if inventory_path.exists() else Inventory()
                journal = root / "knowledge/tool-uses.jsonl"
                events = [structure(json.loads(line), Use) for line in (journal.read_text() if journal.exists() else "").splitlines()]
                validate(inventory, events, set(index(identity)[0]))
                repertoire_plots(inventory, events, destination)

        if "life" in groups:
            write_influences(read_archive(root), destination)

        if "checkpoints" in groups:
            checkpoint_plots(read_checkpoints(root / "knowledge/checkpoints.jsonl"), destination)

        figures = []

        for key in selected:
            # Scan searchable vector labels before rasterization hides them from ordinary text scanners.
            if scan_text((destination / f"{key}.svg").read_text()):
                raise ValueError(f"Personal-data pattern detected in {key}; review plot labels before publishing")

            content = (destination / f"{key}.png").read_bytes()

            if len(content) > MAX_IMAGE_BYTES:
                raise ValueError(f"Figure {key} exceeds the 2 MiB publication limit")

            group, title = FIGURES[key]
            figures.append(Figure(key, group, title, hashlib.sha256(content).hexdigest(), base64.b64encode(content).decode("ascii")))

    payload = (json.dumps(as_data(Bundle(tuple(figures))), sort_keys=True, separators=(",", ":")) + "\n").encode()

    if len(payload) > MAX_BUNDLE_BYTES:
        raise ValueError("Selected figures exceed the 8 MiB bundle limit; publish fewer or smaller figures")

    return payload
