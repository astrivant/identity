"""
Distinguish data-key rewrapping, fresh ciphertext and signature changes while retaining original native history.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

import pytest
from attrs import evolve
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from witful.native import codec
from witful.native.backup import Archive, verify
from witful.native.context import Context
from witful.native.envelope import Signer
from witful.native.rotation import rotate
from witful.native.wire import mapping

from tests.native.runtime import lesson

if TYPE_CHECKING:
    from witful.native.envelope import EnvelopeService

    from tests.native.conftest import Fixture
    from tests.native.runtime import Runtime


def next_keys(fixture: Fixture) -> EnvelopeService:
    """
    Provision synthetic independent next-generation keys while retaining historical generations for recovery.

    Args:
        fixture (Fixture): Test-only key custodian.

    Returns:
        EnvelopeService: Current new generations and separately pinned historical verifiers.
    """
    wrapping, signing = str(uuid4()), str(uuid4())
    fixture.keys.wrapping[wrapping] = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    fixture.keys.signing[signing] = ed25519.Ed25519PrivateKey.generate()
    public = (
        fixture.keys.signing[signing].public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    return evolve(
        fixture.service,
        wrapping=wrapping,
        signing=signing,
        signers={**fixture.service.signers, signing: Signer(public, hashlib.sha256(public).hexdigest())},
    )


@pytest.mark.parametrize("mode", ("rewrap", "reseal", "resign"))
def test_rotation_preserves_history(runtime: Runtime, fixture: Fixture, mode: Literal["rewrap", "reseal", "resign"]) -> None:
    """
    Preserve logical identity and journals while making each representation change measurable.

    Args:
        runtime (Runtime): Real ciphertext backend.
        fixture (Fixture): Synthetic independently retained keys.
        mode (Literal["rewrap", "reseal", "resign"]): Requested distinct rotation contract.

    Returns:
        None: Exact old transactions remain restorable, current content is unchanged and identical retry returns one receipt.
    """
    source, access = runtime.service, runtime.access
    source.append(access, str(uuid4()), "main", None, (lesson(),), b"retained original")
    before = source.history(access, "main")
    old_batches = source.store.history(access.scope)
    old_pointer = before[0][0].payload
    old = mapping(
        codec.decode(source.store.get(access.scope, (old_pointer.object,))[0].payload), {"v", "w", "s", "n", "k", "c", "signature"}
    )
    keys = next_keys(fixture)
    current = evolve(source, keys=lambda _: keys)
    operation = str(uuid4())
    receipt = rotate(current, access, operation, mode)
    assert rotate(current, access, operation, mode) == receipt
    after = current.history(access, "main")
    assert [(item.id, item.parents, item.operation, entry) for item, entry in before] == [
        (item.id, item.parents, item.operation, entry) for item, entry in after
    ]
    pointer = after[0][0].payload
    updated = mapping(
        codec.decode(source.store.get(access.scope, (pointer.object,))[0].payload), {"v", "w", "s", "n", "k", "c", "signature"}
    )
    assert updated["s"] == keys.signing
    if mode == "resign":
        assert updated["w"] == old["w"] and updated["k"] == old["k"]
    else:
        assert updated["w"] == keys.wrapping and updated["k"] != old["k"]
    assert (updated["n"] == old["n"] and updated["c"] == old["c"]) == (mode != "reseal")
    assert current.store.history(access.scope)[: len(old_batches)] == old_batches
    verify(current, access, Archive(access.scope, current.store.history(access.scope)))


def test_signature_rotation_never_requests_unwrap(fixture: Fixture) -> None:
    """
    Verify the signature-only primitive independently of metadata traversal's ordinary read authorization.

    Args:
        fixture (Fixture): Synthetic independent key custody.

    Returns:
        None: A signature-only replacement verifies the old envelope and requests only signing from the custodian.
    """
    context = Context(fixture.context.tenant, fixture.context.identity, str(uuid4()), 3)
    original = fixture.service.seal(context, {"synthetic": 1})
    current = next_keys(fixture)
    fixture.keys.calls.clear()
    changed = current.resign(context, original)
    assert fixture.keys.calls == ["sign"]
    assert current.open(context, changed) == {"synthetic": 1}
