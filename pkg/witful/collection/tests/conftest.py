"""
Build synthetic signed collections for rotation and recipient export integration tests.
"""

from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING, Literal

import pytest
from witful.collection import archive, exports, managed, material, pipeline
from witful.collection.crypto import encrypt, save
from witful.collection.keys import prepare, signing_environment
from witful.collection.managed import PUBLIC, seal_file
from witful.collection.models import CONFIG, FIGURES, SOURCE
from witful.knowledge.contracts import as_data
from witful.project import main as initialize

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch, TempPathFactory

TODAY = date(2030, 1, 1)


@pytest.fixture(scope="module")
def generations(tmp_path_factory: TempPathFactory) -> tuple[Path, Path]:
    """
    Generate two independent synthetic backups for cryptographic integration tests.

    Args:
        tmp_path_factory (TempPathFactory): Test-owned key storage.

    Returns:
        tuple[Path, Path]: Original and replacement key directories.
    """
    root = tmp_path_factory.mktemp("rotation-keys")
    old, new = root / "old", root / "new"
    prepare(old, "example/collection")
    prepare(new, "example/collection")
    return old, new


@pytest.fixture
def collection(tmp_path: Path, generations: tuple[Path, Path], monkeypatch: MonkeyPatch) -> Path:
    """
    Build sources, derived figures, and one opaque export under the old generation.

    Args:
        tmp_path (Path): Synthetic ciphertext and source root.
        generations (tuple[Path, Path]): Independent retained key backups.
        monkeypatch (MonkeyPatch): Isolate host storage attestation, exercised separately in its own tests.

    Returns:
        Path: Three-payload collection with a non-sensitive opaque manifest.
    """
    from witful.collection import operations

    for module in (material, managed, operations, pipeline, exports):
        monkeypatch.setattr(module, "require_protected", lambda path: None)
    root, source, figures = tmp_path / "checkout", tmp_path / "source", tmp_path / "figures"
    root.mkdir()
    (root / ".config").mkdir()
    (root / "collection").mkdir()
    figures.mkdir()
    initialize([str(source)])
    (source / "instructions.md").write_text("SYNTHETIC_ROTATION_RECORD")
    (figures / "provenance.json").write_text('{"source_commit":"synthetic"}')
    old = generations[0]
    config = prepare(old, "example/collection")
    (root / CONFIG).write_text(json.dumps(as_data(config)))
    (root / PUBLIC).write_bytes((old / "cosign.pub").read_bytes())
    entries: tuple[tuple[str, Literal["sources", "figures"], bytes], ...] = (
        (SOURCE, "sources", archive.pack(source)),
        (FIGURES, "figures", archive.pack(figures, figures=True)),
    )
    for relative, purpose, payload in entries:
        save(
            root,
            relative,
            encrypt(payload, (old / "collection.pub").read_bytes(), config, purpose),
            (old / "cosign.pub").read_bytes(),
            config,
            signing_environment(old),
        )
    extra = tmp_path / "private-export.bin"
    extra.write_bytes(b"opaque\0SYNTHETIC_EXPORT")
    seal_file(root, extra, old, "export-01", TODAY)
    return root
