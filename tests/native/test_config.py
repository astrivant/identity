"""
Verify that deployment evidence is independent, exact-configuration-bound, expiring and required before key access.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from attrs import evolve
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native import codec
from witful.native.config import TLS, Backend, Broker, Evidence, Probe, Protection, Settings, Trust, load, require_profile
from witful.native.values import pack

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """
    Create synthetic operator evidence without claiming any real deployment satisfies its controls.

    Args:
        tmp_path (Path): Synthetic evidence workspace.

    Returns:
        Settings: Exact configured test values with a separate freshly generated attester key.
    """
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    signing = str(uuid4())
    broker_public = (
        Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    trust = Trust(signing, base64.b64encode(broker_public).decode(), hashlib.sha256(broker_public).hexdigest())
    value = Settings(
        Backend(str(uuid4())),
        TLS("server.pem", "server.key", "ca.pem", "localhost", "client.pem", "client.key"),
        Broker("https://broker.invalid", "ca.pem", "client.pem", "client.key", str(uuid4()), signing, str(uuid4()), str(uuid4()), (trust,)),
        Probe(str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4()), 1, str(uuid4())),
        Protection(str(tmp_path / "evidence.cbor"), base64.b64encode(public).decode(), hashlib.sha256(public).hexdigest()),
    )
    controls = (
        "data-volume-encryption",
        "authority-volume-encryption",
        "wal-and-backup-encryption",
        "temp-memory-noswap",
        "core-dumps-disabled",
        "tls",
        "role-separation",
        "old-primary-fencing",
        "recovery-tested",
    )
    evidence = Evidence(
        hashlib.sha256(codec.encode(pack(as_data(value)))).hexdigest(),
        100,
        200,
        controls,
        ("Synthetic evidence contract; no production protection asserted",),
    )
    payload = codec.encode(as_data(evidence))
    (tmp_path / "evidence.cbor").write_bytes(
        codec.encode({"payload": payload, "signature": private.sign(b"witful-storage-evidence-v1\0" + payload)})
    )
    return value


def test_protection_evidence_requires_current_exact_configuration(settings: Settings) -> None:
    """
    Reject expired, premature, altered-config and untrusted attestation inputs.

    Args:
        settings (Settings): Independently signed synthetic profile.

    Returns:
        None: A signature cannot authorize another configuration or an expired observation.
    """
    assert require_profile(settings, 150).expires == 200
    for moment in (99, 200, 201):
        with pytest.raises(NativeError):
            require_profile(settings, moment)
    changed = evolve(settings, backend=evolve(settings.backend, id=str(uuid4())))
    with pytest.raises(NativeError, match="conflict"):
        require_profile(changed, 150)
    changed = evolve(settings, protection=evolve(settings.protection, fingerprint="0" * 64))
    with pytest.raises(NativeError, match="denied"):
        require_profile(changed, 150)


def test_configuration_errors_do_not_disclose_values(settings: Settings, tmp_path: Path) -> None:
    """
    Keep malformed user configuration out of diagnostics and reject unsupported fields.

    Args:
        settings (Settings): Synthetic settings.
        tmp_path (Path): Test input directory.

    Returns:
        None: Diagnostics remain bounded and credential-safe.
    """
    value = as_data(settings)
    value["unexpected"] = "synthetic-private-config-canary"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(value))
    with pytest.raises(NativeError) as failure:
        load(path)
    assert "canary" not in str(failure.value)
    assert "unexpected" not in str(failure.value)
