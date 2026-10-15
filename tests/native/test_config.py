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

    from tests.native.database import Databases
    from tests.native.runtime import Runtime


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


def test_recipient_configuration_is_scoped_and_pinned(settings: Settings, tmp_path: Path) -> None:
    """
    Reject duplicate aliases, wrong public-key fingerprints and malformed scopes before a controller starts.

    Args:
        settings (Settings): Synthetic complete operator configuration.
        tmp_path (Path): Synthetic reviewed configuration file.

    Returns:
        None: Only closed, scoped public encryption recipients are accepted.
    """
    from cryptography.hazmat.primitives.asymmetric import rsa
    from witful.native.config import ExportRecipient

    public = (
        rsa.generate_private_key(public_exponent=65537, key_size=3072)
        .public_key()
        .public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    recipient = ExportRecipient(
        "reviewer",
        settings.probe.tenant,
        settings.probe.identity,
        str(uuid4()),
        base64.b64encode(public).decode(),
        hashlib.sha256(public).hexdigest(),
    )
    configured = evolve(settings, recipients=(recipient,))
    path = tmp_path / "config.json"
    path.write_text(json.dumps(as_data(configured)))
    assert load(path) == configured
    for recipients in (
        (recipient, recipient),
        (evolve(recipient, fingerprint="0" * 64),),
        (evolve(recipient, identity="not-a-uuid"),),
        (evolve(recipient, public="invalid-base64"),),
    ):
        path.write_text(json.dumps(as_data(evolve(settings, recipients=recipients))))
        with pytest.raises(NativeError):
            load(path)


def test_gateway_configuration_separates_remote_privilege(settings: Settings, tmp_path: Path) -> None:
    """
    Reject mixed controller/gateway roles and unsafe remote credential routing before any service starts.

    Args:
        settings (Settings): Synthetic complete signed-settings shape.
        tmp_path (Path): Disposable configuration file.

    Returns:
        None: Only the explicit single-writer SSH gateway configuration is admitted.
    """
    from witful.native.config import GatewayRemote

    remote = GatewayRemote(
        str(uuid4()),
        settings.probe.tenant,
        settings.probe.identity,
        "ssh://git@git.example.invalid/approved/identity.git",
        "refs/heads/projection",
        "/run/witful/destination",
        "/etc/git/key",
        "/etc/git/known_hosts",
    )
    configured = evolve(settings, role="projection", gateway=(remote,), probe=evolve(settings.probe, envelope="/etc/probe/envelope.cbor"))
    path = tmp_path / "gateway.json"
    path.write_text(json.dumps(as_data(configured)))
    assert load(path) == configured
    rejected = (
        evolve(configured, role="controller"),
        evolve(configured, runtime=evolve(configured.runtime, workers=2)),
        evolve(configured, gateway=(remote, remote)),
        evolve(configured, gateway=(evolve(remote, url="https://user:password@example.invalid/repository"),)),
        evolve(configured, gateway=(evolve(remote, directory="/run/witful/../outside"),)),
        evolve(configured, gateway=(evolve(remote, directory="/tmp/unreviewed"),)),
        evolve(configured, probe=evolve(configured.probe, envelope="")),
    )
    for candidate in rejected:
        path.write_text(json.dumps(as_data(candidate)))
        with pytest.raises(NativeError):
            load(path)


def test_gateway_readiness_uses_only_current_permit_decryption(
    settings: Settings,
    runtime: Runtime,
    databases: Databases,
    tmp_path: Path,
) -> None:
    """
    Verify real independent grant and key availability without requiring gateway signing or native data-store access.

    Args:
        settings (Settings): Synthetic deployment settings shape.
        runtime (Runtime): Actual Git or PostgreSQL authority fixture.
        databases (Databases): Synthetic independent grant administrator.
        tmp_path (Path): Encrypted readiness probe directory.

    Returns:
        None: A valid permit probe passes while wrong kinds and revoked grants fail; no domain unwrap is attempted.
    """
    import psycopg
    from witful.native.api.admission import Admission
    from witful.native.context import Context
    from witful.native.projection.application import Readiness
    from witful.native.projection.gateway import Gateway
    from witful.native.projection.models import PERMIT

    from tests.native.projection import PermitKeys, configured

    service = configured(runtime, databases)
    original = service.keys(runtime.access)
    restricted = PermitKeys(original.keys, [])
    keys = evolve(original, keys=restricted)
    path = tmp_path / "probe.cbor"
    context = Context(runtime.access.scope.tenant, runtime.access.scope.identity, str(uuid4()), PERMIT)
    path.write_bytes(codec.encode({"context": context.data(), "sealed": original.seal(context, {"probe": 1})}))
    selected = evolve(settings, probe=evolve(settings.probe, envelope=str(path)))
    gateway = Gateway(service.authority, (), lambda _: keys, lambda: None, service.budget)
    assert Readiness(selected, gateway, Admission(1), runtime.access)()
    assert restricted.observed == [PERMIT]
    wrong = evolve(context, kind=1)
    path.write_bytes(codec.encode({"context": wrong.data(), "sealed": original.seal(wrong, {"probe": 1})}))
    assert not Readiness(selected, gateway, Admission(1), runtime.access)()
    assert restricted.observed == [PERMIT]
    path.write_bytes(codec.encode({"context": context.data(), "sealed": original.seal(context, {"probe": 1})}))
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute("DELETE FROM witful_native_grants WHERE id=%s", (runtime.access.grant,))
    assert not Readiness(selected, gateway, Admission(1), runtime.access)()
