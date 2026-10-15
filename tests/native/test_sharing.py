"""
Verify independent recipient recovery, preserved history, current export admission and complete object accounting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from attrs import evolve
from witful.exceptions import NativeError
from witful.native import codec, original_git
from witful.native.backup import Archive, inspect
from witful.native.context import Context
from witful.native.models import Frontier, Pointer, parse
from witful.native.rotation import rotate
from witful.native.service import FRONTIER
from witful.native.sharing import SendingKeys, create, open_disclosure
from witful.native.storage import Object

from tests.native.original import source_repository
from tests.native.recipients import receiver
from tests.native.runtime import lesson

if TYPE_CHECKING:
    from pathlib import Path

    from tests.native.conftest import Fixture
    from tests.native.runtime import Runtime


def test_recipient_reads_complete_history_without_sender_keys(runtime: Runtime, fixture: Fixture) -> None:
    """
    Preserve original receipts, representations and source bytes through rotation while enabling independent recipient reads.

    Args:
        runtime (Runtime): Actual native Git or PostgreSQL authority.
        fixture (Fixture): Synthetic sender custody, removed after export.

    Returns:
        None: The recipient verifies complete history without any sender key or live service read.
    """
    service, access = runtime.service, runtime.access
    source = b' { "original": "synthetic-source-canary" }\r\n'
    entry = lesson("synthetic-recipient-canary")
    service.append(access, str(uuid4()), "main", None, (entry,), source)
    rotate(service, access, str(uuid4()), "reseal")
    original = service.store.history(access.scope)
    recipient, reader = receiver(fixture)
    context, sealed = create(service, access, recipient)
    header = reader.verify(context, sealed)
    assert header["s"] == fixture.service.signing and header["w"] == recipient.generation
    assert b"synthetic-recipient-canary" not in sealed and b"synthetic-source-canary" not in sealed

    # Remove the original custody entirely. Verification and subsequent reads must use only the recipient package.
    fixture.keys.wrapping.clear()
    fixture.keys.signing.clear()
    fixture.keys.calls.clear()
    disclosure = open_disclosure(context, sealed, reader)
    assert disclosure.archive.batches == original
    head = disclosure.archive.head
    assert head.root is not None
    frontier = parse(disclosure.view.open(Pointer(head.root, head.root, FRONTIER, head.digest.hex())), Frontier)
    history = disclosure.view.lineage(frontier, frontier.refs[0].revision)
    assert history[0][1] == entry
    original_pointer = history[0][0].source
    assert original_pointer is not None and disclosure.view.open(original_pointer) == source
    assert not fixture.keys.calls


def test_default_disclosure_uses_current_custody(runtime: Runtime, fixture: Fixture) -> None:
    """
    Preserve default owner encryption and original sender signing without requiring a recipient override.

    Args:
        runtime (Runtime): Real admitted native source.
        fixture (Fixture): Current operational keys.

    Returns:
        None: The default profile carries an independently verified complete snapshot.
    """
    service, access = runtime.service, runtime.access
    service.append(access, str(uuid4()), "main", None, (lesson(),))
    context, sealed = create(service, access)
    assert fixture.service.verify(context, sealed)["w"] == fixture.service.wrapping
    assert open_disclosure(context, sealed, fixture.service).archive.head == service.store.head(access.scope)


@pytest.mark.parametrize("defect", ("key", "missing", "extra", "scope", "duplicate"))
def test_signed_but_incoherent_disclosure_is_refused(runtime: Runtime, fixture: Fixture, defect: str) -> None:
    """
    Require complete exact key-to-record bindings even when an outer payload has a valid sender signature.

    Args:
        runtime (Runtime): Actual synthetic source.
        fixture (Fixture): Test sender able to sign intentionally malformed packages.
        defect (str): Independently corrupted manifest property.

    Returns:
        None: Missing, substituted, excessive or duplicated key claims never produce a verified disclosure.
    """
    service, access = runtime.service, runtime.access
    service.append(access, str(uuid4()), "main", None, (lesson(),))
    context, sealed = create(service, access)
    body = fixture.service.open(context, sealed)
    assert isinstance(body, dict) and isinstance(body["keys"], list)
    slots = body["keys"]
    assert isinstance(slots[0], dict)
    first = slots[0]
    if defect == "key":
        first["key"] = b"\0" * 32
    elif defect == "missing":
        slots.pop()
    elif defect == "extra":
        slots.append({**first, "generation": str(uuid4())})
    elif defect == "scope":
        assert isinstance(first["context"], dict)
        first["context"]["identity"] = str(uuid4())
    else:
        slots.append(dict(first))
    with pytest.raises(NativeError):
        open_disclosure(context, fixture.service.seal(context, body), fixture.service)


def test_recipient_key_context_and_sender_pin_are_independent(runtime: Runtime, fixture: Fixture) -> None:
    """
    Reject a different recipient, context or sender pin before releasing any historical data.

    Args:
        runtime (Runtime): Admitted synthetic source.
        fixture (Fixture): Current sender custody and trust.

    Returns:
        None: Recipient replacement and forged framing cannot establish sender trust.
    """
    recipient, reader = receiver(fixture)
    context, sealed = create(runtime.service, runtime.access, recipient)
    _, wrong = receiver(fixture)
    with pytest.raises(NativeError):
        open_disclosure(context, sealed, evolve(wrong, wrapping=recipient.generation))
    with pytest.raises(NativeError):
        open_disclosure(evolve(context, identity=str(uuid4())), sealed, reader)
    with pytest.raises(NativeError):
        evolve(reader, signers={reader.signing: evolve(reader.signers[reader.signing], fingerprint="0" * 64)})
    value = codec.decode(sealed)
    assert isinstance(value, dict) and isinstance(value["signature"], bytes)
    value["signature"] = b"\0" * 64
    with pytest.raises(NativeError):
        open_disclosure(context, codec.encode(value), reader)
    # Selecting a recipient changes encryption only; the recipient cannot create a valid sender signature.
    with pytest.raises(NativeError):
        reader.seal(context, {})
    with pytest.raises(NativeError):
        SendingKeys(fixture.keys, recipient).invoke("unwrap", recipient.generation, context, b"unused")


def test_backup_refuses_unexplained_stored_objects(runtime: Runtime, fixture: Fixture) -> None:
    """
    Catch ciphertext outside the authenticated inventory instead of claiming full-history coverage.

    Args:
        runtime (Runtime): Real source with one complete transaction.
        fixture (Fixture): Synthetic signer capable of constructing an unrelated valid envelope.

    Returns:
        None: A signed but unreferenced extra object fails the complete-backup contract.
    """
    service, access = runtime.service, runtime.access
    service.append(access, str(uuid4()), "main", None, (lesson(),))
    batch = service.store.history(access.scope)[0]
    unrelated = Object(
        str(uuid4()), fixture.service.seal(Context(access.scope.tenant, access.scope.identity, str(uuid4()), 5), b"unexplained")
    )
    archive = Archive(access.scope, (evolve(batch, objects=(*batch.objects, unrelated)),))
    with pytest.raises(NativeError, match="incomplete"):
        inspect(archive, fixture.service, service.budget, service.monotonic)


def test_recipient_recovers_original_git_bytes(runtime: Runtime, fixture: Fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Recover all original Git object and metadata chunks using only the independent recipient package.

    Args:
        runtime (Runtime): Actual encrypted source backend.
        fixture (Fixture): Sender custody removed after creating the disclosure.
        tmp_path (Path): Disposable synthetic original source.
        monkeypatch (pytest.MonkeyPatch): Synthetic-only volume attestation stand-in.

    Returns:
        None: Original object IDs and bytes remain verifiable without the original broker or signing key.
    """
    monkeypatch.setattr(original_git, "require_protected", lambda _: None)
    directory = tmp_path / "original.git"
    original_commit, original_tag = source_repository(directory)
    original_git.capture(runtime.service, runtime.access, str(uuid4()), directory, True, True)
    recipient, reader = receiver(fixture)
    context, sealed = create(runtime.service, runtime.access, recipient)
    fixture.keys.wrapping.clear()
    fixture.keys.signing.clear()
    disclosure = open_disclosure(context, sealed, reader)
    head = disclosure.archive.head
    assert head.root is not None
    frontier = parse(disclosure.view.open(Pointer(head.root, head.root, FRONTIER, head.digest.hex())), Frontier)
    pointer = next(item for item in frontier.archives if item.kind == original_git.GIT_ARCHIVE)
    repository = parse(disclosure.view.open(pointer), original_git.Repository)
    objects, metadata = original_git.validate_view(disclosure.view, repository)
    assert original_commit in {item.oid for item in repository.objects}
    assert original_tag in {item.oid for item in repository.objects}
    assert any(b"gpgsig" in payload for _, payload in objects)
    assert any(name == "custom-recovery-receipt" for name, _, _ in metadata)
