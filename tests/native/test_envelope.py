"""
Verify randomized records, context isolation, signer pins and retained-history rotation.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from attrs import evolve
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from witful.exceptions import NativeError
from witful.native import codec
from witful.native.envelope import Signer

if TYPE_CHECKING:
    from tests.native.conftest import Fixture


def test_round_trip_and_randomized_ciphertext(fixture: Fixture) -> None:
    """
    Preserve logical bytes while ensuring separate representations have fresh encryption randomness.

    Args:
        fixture (Fixture): Generated private custody and independently pinned verifier.

    Returns:
        None: Ciphertext differs across seals and contains no source text or semantic digest.
    """
    value = {"body": "synthetic-private-canary", "parents": [str(uuid4())], "original": b'{  "a":1 }\r\n'}
    first, second = fixture.service.seal(fixture.context, value), fixture.service.seal(fixture.context, value)
    assert first != second
    assert b"synthetic-private-canary" not in first
    assert codec.digest(value) not in first
    assert fixture.service.open(fixture.context, first) == value
    assert fixture.service.open(fixture.context, second) == value
    assert fixture.service.verify(fixture.context, first)["n"] != fixture.service.verify(fixture.context, second)["n"]


def test_context_substitution_precedes_unwrap(fixture: Fixture) -> None:
    """
    Deny storage-supplied context substitution before accessing any private recovery key.

    Args:
        fixture (Fixture): Independent signing and wrapping test generations.

    Returns:
        None: Cross-tenant, identity, revision and kind confusion fails signature verification.
    """
    envelope = fixture.service.seal(fixture.context, {"body": "canary"})
    contexts = [
        evolve(fixture.context, tenant=str(uuid4())),
        evolve(fixture.context, identity=str(uuid4())),
        evolve(fixture.context, record=str(uuid4())),
        evolve(fixture.context, kind=2),
    ]
    fixture.keys.calls.clear()
    for context in contexts:
        with pytest.raises(NativeError):
            fixture.service.open(context, envelope)
    assert not fixture.keys.calls


@pytest.mark.parametrize("name", ["w", "s", "n", "k", "c", "signature"])
def test_tamper_fails_before_key_access(fixture: Fixture, name: str) -> None:
    """
    Authenticate every key selector and encrypted framing field before private-key access.

    Args:
        fixture (Fixture): Synthetic cryptographic environment.
        name (str): Envelope field to substitute.

    Returns:
        None: Corrupted representations release no plaintext and make no recovery request.
    """
    envelope = fixture.service.seal(fixture.context, {"body": "canary"})
    value = codec.decode(envelope)
    assert isinstance(value, dict)
    previous = value[name]
    value[name] = str(uuid4()) if isinstance(previous, str) else b"\x00" * len(previous)
    fixture.keys.calls.clear()
    with pytest.raises(NativeError):
        fixture.service.open(fixture.context, codec.encode(value))
    assert not fixture.keys.calls


def test_rotation_retains_old_representations(fixture: Fixture) -> None:
    """
    Distinguish wrapping rotation from fresh content encryption and keep historical verification available.

    Args:
        fixture (Fixture): Synthetic custody with one original generation.

    Returns:
        None: Original, rewrapped and resealed records recover the same exact value under retained trust.
    """
    original = fixture.service.seal(fixture.context, {"source": b"original historical bytes"})
    wrapping, signing = str(uuid4()), str(uuid4())
    fixture.keys.wrapping[wrapping] = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    fixture.keys.signing[signing] = ed25519.Ed25519PrivateKey.generate()
    public = (
        fixture.keys.signing[signing].public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    signers = {**fixture.service.signers, signing: Signer(public, hashlib.sha256(public).hexdigest())}
    current = evolve(fixture.service, wrapping=wrapping, signing=signing, signers=signers)
    signers.clear()
    rewrapped = current.rewrap(fixture.context, original)
    resealed = current.reseal(fixture.context, original)
    old, wrap, seal = [current.verify(fixture.context, item) for item in (original, rewrapped, resealed)]
    assert (old["n"], old["c"]) == (wrap["n"], wrap["c"])
    assert old["k"] != wrap["k"]
    assert (old["n"], old["c"]) != (seal["n"], seal["c"])
    assert current.open(fixture.context, original) == current.open(fixture.context, rewrapped) == current.open(fixture.context, resealed)
    with pytest.raises(NativeError):
        evolve(current, signers={signing: Signer(public, "0" * 64)})
