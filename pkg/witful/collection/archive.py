"""
Serialize only reviewed collection sources and reject unsafe archive paths before writing.
"""

from __future__ import annotations

import base64
import json
import re
from typing import TYPE_CHECKING

from witful.checkpoints.journal import read as read_checkpoints
from witful.collection.models import MAX_BYTES
from witful.instances.journal import check_references
from witful.instances.journal import read as read_instances
from witful.knowledge.applications import read_applications, validate_applications
from witful.knowledge.compiler import compile_identity, index
from witful.knowledge.contracts import structure
from witful.knowledge.models import Catalog
from witful.lessons import read_journal
from witful.life.contracts import canonical
from witful.life.journal import read_archive
from witful.repertoire.journal import validate as validate_repertoire
from witful.repertoire.models import Inventory, Use

if TYPE_CHECKING:
    from pathlib import Path

SOURCES = (
    "lessons.jsonl",
    "knowledge/catalog.json",
    "knowledge/context.json",
    "knowledge/applications.jsonl",
    "knowledge/life.jsonl",
    "knowledge/checkpoints.jsonl",
    "knowledge/instances.jsonl",
    "knowledge/repertoire.json",
    "knowledge/tool-uses.jsonl",
    "instructions.md",
)


def allowed(name: str, *, figures: bool = False) -> bool:
    """
    Match an exact source allowlist or fixed generated figure namespace.

    Args:
        name (str): Untrusted archive member name.
        figures (bool): Select the generated output contract instead of source inputs.

    Returns:
        bool: Whether the relative name belongs to this archive type.
    """
    if figures:
        from witful.awareness.models import FIGURES

        return name == "provenance.json" or name in {f"{key}.{suffix}" for key in FIGURES for suffix in ("png", "svg")}

    return (
        name in SOURCES
        or re.fullmatch(r"knowledge/snapshots/[0-9a-f]{64}\.json", name) is not None
        or re.fullmatch(r"knowledge/schemas/[a-z-]+\.schema\.json", name) is not None
    )


def validate(root: Path) -> None:
    """
    Check all supported source contracts before encryption or rendering.

    Args:
        root (Path): Decrypted local collection.

    Returns:
        None: Journals, hierarchy, references, decision chain, and checkpoints validate.
    """
    catalog = structure(json.loads((root / "knowledge/catalog.json").read_text()), Catalog)
    identity = compile_identity(read_journal(root / "lessons.jsonl"), catalog)
    # Reviewed context mappings travel with sources; private runtime receipts never enter the archive.
    context_path = root / "knowledge/context.json"
    if context_path.exists():
        from witful.context.models import Mapping

        structure(json.loads(context_path.read_text()), Mapping)
    validate_applications(identity, read_applications(root / "knowledge/applications.jsonl"))
    read_archive(root)
    read_checkpoints(root / "knowledge/checkpoints.jsonl")
    check_references(root, read_instances(root))
    inventory_path = root / "knowledge/repertoire.json"
    inventory = structure(json.loads(inventory_path.read_text()), Inventory) if inventory_path.exists() else Inventory()
    journal = root / "knowledge/tool-uses.jsonl"
    events = [structure(json.loads(line), Use) for line in (journal.read_text() if journal.exists() else "").splitlines()]
    validate_repertoire(inventory, events, set(index(identity)[0]))


def pack(root: Path, *, figures: bool = False) -> bytes:
    """
    Build a bounded file map without copying runtime files, credentials, or arbitrary configuration.

    Args:
        root (Path): Local source collection or generated figure directory.
        figures (bool): Select only known plot filenames when true.

    Returns:
        bytes: Canonical map of allowlisted paths to base64 file contents.

    Raises:
        ValueError: A selected source is a symlink or the collection is too large.
    """
    candidates = (
        root.glob("*")
        if figures
        else [
            *(root / name for name in SOURCES if (root / name).exists()),
            *(root / "knowledge/snapshots").glob("*.json"),
            *(root / "knowledge/schemas").glob("*.schema.json"),
        ]
    )
    names = sorted(path.relative_to(root).as_posix() for path in candidates if allowed(path.relative_to(root).as_posix(), figures=figures))
    content: dict[str, str] = {}
    size = 0

    for name in names:
        path = root / name

        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Collection inputs must be regular files inside their root")

        size += path.stat().st_size

        if size > MAX_BYTES // 2:
            raise ValueError("Collection files exceed the 16 MiB archive input limit")

        content[name] = base64.b64encode(path.read_bytes()).decode("ascii")

    return canonical(content)


def unpack(data: bytes, root: Path, *, figures: bool = False) -> None:
    """
    Validate the entire authenticated map before extracting to a new private directory.

    Args:
        data (bytes): Decrypted JSON map.
        root (Path): New destination; existing paths are never overwritten.
        figures (bool): Require the figure-only namespace when true.

    Returns:
        None: Private regular files are installed under the new directory.

    Raises:
        ValueError: Names, value types, or total size violate the selected archive contract.
    """
    if len(data) > MAX_BYTES or root.exists():
        raise ValueError("Restore needs a new directory and a bounded archive")

    decoded: object = json.loads(data)

    if not isinstance(decoded, dict) or len(decoded) > 10000:
        raise ValueError("Invalid collection file map")

    files: dict[str, bytes] = {}

    for name, value in decoded.items():
        if not isinstance(name, str) or not allowed(name, figures=figures) or not isinstance(value, str):
            raise ValueError("Archive contains an unexpected path or value")
        files[name] = base64.b64decode(value, validate=True)

    if sum(map(len, files.values())) > MAX_BYTES // 2:
        raise ValueError("Archive files exceed the extraction limit")

    root.mkdir(parents=True, mode=0o700)

    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(content)
        path.chmod(0o600)
