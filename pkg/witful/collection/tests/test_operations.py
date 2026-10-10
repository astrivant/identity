"""
Exercise a complete signed, encrypted private collection round trip with fake GitHub boundaries.
"""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING

import pytest
from witful.collection import operations
from witful.collection.crypto import verify
from witful.collection.keys import prepare, signing_environment
from witful.collection.models import CONFIG, FIGURES, SOURCE
from witful.collection.operations import readme, refresh, restore, seal
from witful.knowledge.contracts import as_data
from witful.project import main as initialize

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


@pytest.mark.skipif(shutil.which("cosign") is None, reason="Cosign is installed by CI; required for the offline signature contract")
def test_signed_refresh_round_trip(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Rebuild from a new collection while keeping records out of Git outputs and rejecting altered signatures.

    Args:
        tmp_path (Path): Isolated synthetic home, repository, keys, and runner scratch space.
        monkeypatch (MonkeyPatch): GitHub visibility boundary and trusted CI event environment.

    Returns:
        None: Full sources and all figures recover after signature verification, without retained plaintext CI files.
    """
    monkeypatch.setattr(operations, "private_repository", lambda repository: None)
    source, checkout, keys = tmp_path / "home/collection", tmp_path / "checkout", tmp_path / "keys"
    initialize([str(source)])
    (source / "instructions.md").write_text("SYNTHETIC_PRIVATE_SENTINEL")
    checkout.mkdir()
    (checkout / ".config").mkdir()
    (checkout / "collection").mkdir()
    config = prepare(keys, "example/collection")
    assert prepare(keys, "example/collection") == config
    (checkout / CONFIG).write_text(json.dumps(as_data(config)))
    (checkout / "collection/cosign.pub").write_bytes((keys / "cosign.pub").read_bytes())
    seal(checkout, source, keys)
    restore(checkout, keys, tmp_path / "recovered", "sources")
    assert (tmp_path / "recovered/instructions.md").read_text() == "SYNTHETIC_PRIVATE_SENTINEL"
    assert (tmp_path / "recovered/knowledge/schemas/catalog.schema.json").exists()

    for name, value in signing_environment(keys).items():
        if name.startswith("COSIGN_"):
            monkeypatch.setenv(name, value)

    for name, value in {
        "GITHUB_REPOSITORY": "example/collection",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/main",
        "WITFUL_COLLECTION_PRIVATE_KEY": (keys / "collection.key").read_text(),
        "WITFUL_COLLECTION_PUBLIC_KEY": (keys / "collection.pub").read_text(),
        "WITFUL_COLLECTION_KEY_PASSWORD": (keys / "collection.password").read_text(),
        "RUNNER_TEMP": str(tmp_path),
    }.items():
        monkeypatch.setenv(name, value)

    refresh(checkout)
    assert not list(tmp_path.glob("witful-plain-*"))
    assert not (checkout / "docs/collection").exists()
    assert "figures.enc.json" in (checkout / "README.md").read_text()
    assert all(b"SYNTHETIC_PRIVATE_SENTINEL" not in path.read_bytes() for path in checkout.rglob("*") if path.is_file())
    restore(checkout, keys, tmp_path / "plots", "figures")
    assert len(list((tmp_path / "plots").glob("*.png"))) == 7
    assert len(list((tmp_path / "plots").glob("*.svg"))) == 7
    verify(checkout / FIGURES, checkout / "collection/cosign.pub", config)

    # Both ciphertext and its checksum may be attacker-controlled; the independent signature still rejects changes.
    path = checkout / SOURCE
    path.write_bytes(path.read_bytes() + b" ")

    with pytest.raises(ValueError):
        restore(checkout, keys, tmp_path / "untrusted", "sources")

    assert not (tmp_path / "untrusted").exists()
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")

    with pytest.raises(ValueError, match="private main"):
        refresh(checkout)


def test_private_dashboard_has_no_author_data() -> None:
    """
    Replace the upstream README with repository-specific operational links and encrypted defaults.

    Returns:
        None: No label, source content, or upstream CI badge substitutes for the owner's collection.
    """
    from witful.collection.models import Config

    config = Config("example/private-collection", "a" * 64, "b" * 64)
    text = readme(config, "c" * 64)
    assert "example/private-collection/actions" in text
    assert "![Knowledge" not in text
    assert "restore" in text
