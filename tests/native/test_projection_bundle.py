"""
Validate deterministic projection objects through real Git, including exact parents, bytes and rejected metadata substitution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from attrs import evolve
from witful.exceptions import NativeError
from witful.native import codec
from witful.native.git import git
from witful.native.projection.bundle import Bundle, prepare, validate

if TYPE_CHECKING:
    from pathlib import Path


def test_prepared_git_objects_round_trip_without_remote_io(tmp_path: Path) -> None:
    """
    Insert prepared objects through Git's normal parser, check connectivity and recover exact sidecar bytes and ancestry.

    Args:
        tmp_path (Path): Disposable bare synthetic repository.

    Returns:
        None: Pure preparation matches actual Git object identities and deterministic binary serialization.
    """
    git(tmp_path, ("init", "--bare", "--template=", "."))
    parent = None
    for _ in range(2):
        operation = str(uuid4())
        bundle = prepare(
            b"synthetic-encrypted-sidecar-placeholder", operation, parent, "Projection Contract", "fixture@example.invalid", 100
        )
        assert prepare(bundle.blob, operation, parent, "Projection Contract", "fixture@example.invalid", 100) == bundle
        assert Bundle.decode(bundle.encode(codec.DEFAULT_LIMITS), codec.DEFAULT_LIMITS) == bundle
        validate(bundle, operation, parent, "Projection Contract", "fixture@example.invalid", 100)
        for kind, oid, payload in bundle.objects():
            assert git(tmp_path, ("hash-object", "-t", kind, "-w", "--stdin"), payload).strip().decode() == oid
            assert git(tmp_path, ("cat-file", kind, oid)) == payload
        commit = bundle.objects()[-1][1]
        git(tmp_path, ("update-ref", "refs/heads/projection", commit, parent or "0" * 40))
        git(tmp_path, ("fsck", "--strict", "--full", "--no-reflogs"))
        assert git(tmp_path, ("show", f"{commit}:native.cbor")) == bundle.blob
        assert git(tmp_path, ("rev-list", "--parents", "-1", commit)).strip().decode().split() == [commit, *([parent] if parent else [])]
        with pytest.raises(NativeError):
            validate(evolve(bundle, tree=bundle.tree + b"extra"), operation, parent, "Projection Contract", "fixture@example.invalid", 100)
        with pytest.raises(NativeError):
            validate(bundle, operation, parent, "Projection Contract", "fixture@example.invalid", 101)
        parent = commit


@pytest.mark.parametrize("author,email", (("Injected\nparent", "fixture@example.invalid"), ("Safe", "extra header"), ("<wrong>", "safe")))
def test_projection_metadata_cannot_inject_git_headers(author: str, email: str) -> None:
    """
    Reject control characters and delimiter substitution before generating any Git object.

    Args:
        author (str): Individually malformed exporter name or companion value.
        email (str): Individually malformed contact or companion value.

    Returns:
        None: Invalid metadata cannot add parents, headers or ambiguous attribution.
    """
    with pytest.raises(NativeError):
        prepare(b"synthetic", str(uuid4()), None, author, email, 100)
