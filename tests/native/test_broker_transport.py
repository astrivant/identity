"""
Exercise the released broker server and standalone SDK over real mutual TLS with synthetic provider custody.
"""

from __future__ import annotations

import base64
import hashlib
import ssl
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from agent_broker import contracts
from agent_broker.api.server import BrokerServer
from agent_broker.approval import write_private
from agent_broker.crypto.models import Grant, Key, Policy
from agent_broker.crypto.service import CryptoService
from agent_broker.lifecycle import running
from agent_broker.models import Credential
from agent_broker.testing.scenario import SyntheticProvider, scenario
from agent_broker_sdk.client import CryptoClient
from attrs import evolve
from cryptography.hazmat.primitives import serialization
from witful.exceptions import NativeError
from witful.native.broker import BrokerKeys

from tests.native.runtime import lesson

if TYPE_CHECKING:
    from pathlib import Path

    from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

    from tests.native.conftest import Fixture
    from tests.native.runtime import Runtime


def test_native_records_use_released_sdk_over_mtls(runtime: Runtime, fixture: Fixture, tmp_path: Path) -> None:
    """
    Require an enrolled certificate and current broker grant for actual native writes and reads through the released SDK.

    Args:
        runtime (Runtime): Real native data/control boundary with synthetic grants.
        fixture (Fixture): Independently held synthetic cryptographic keys and verification pins.
        tmp_path (Path): Disposable synthetic policy and certificate workspace.

    Returns:
        None: Real service/client TLS round trips preserve records; certificate substitution, revocation and outage fail closed.
    """
    root = tmp_path / "broker"
    root.mkdir()
    access = runtime.access
    authority, policy_revision = str(uuid4()), str(uuid4())
    keys: dict[str, rsa.RSAPrivateKey | ed25519.Ed25519PrivateKey] = {**fixture.keys.wrapping, **fixture.keys.signing}
    secrets = {
        "op://synthetic/" + generation + "/key": base64.b64encode(
            key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        ).decode()
        for generation, key in keys.items()
    }
    configured = {
        generation: Key(
            Credential("op://synthetic/" + generation + "/key"),
            "wrapping" if generation in fixture.keys.wrapping else "signing",
            hashlib.sha256(
                key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
            ).hexdigest(),
        )
        for generation, key in keys.items()
    }
    policy_path = root / "crypto.json"
    with scenario(root) as application:
        fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert((root / "alpha.pem").read_text())).hexdigest()
        grant = Grant(
            fingerprint,
            access.scope.tenant,
            access.scope.identity,
            access.task,
            authority,
            policy_revision,
            ("wrap", "unwrap", "sign"),
            tuple(keys),
            4102444800,
            all_records=True,
        )
        policy = Policy(configured, {access.grant: grant})
        write_private(policy_path, contracts.data(policy))
        provider = SyntheticProvider(secrets, [])
        crypto = CryptoService(policy_path, provider, application.broker.ledger)
        server = BrokerServer(
            ("127.0.0.1", 0), application.broker, root / "server.pem", root / "server.key", root / "ca.pem", crypto=crypto
        )
        with running(server):
            url = f"https://localhost:{server.server_port}"
            client = CryptoClient(url, root / "ca.pem", root / "alpha.pem", root / "alpha.key")
            custody = BrokerKeys(client, access.grant, access.task, authority, policy_revision)
            envelope = evolve(fixture.service, keys=custody)
            service = evolve(runtime.service, keys=lambda _: envelope)
            service.append(access, str(uuid4()), "main", None, (lesson(),))
            record = service.history(access, "main")[0][0].id
            assert service.read(access, record) == lesson()
            denied_client = CryptoClient(url, root / "ca.pem", root / "bravo.pem", root / "bravo.key")
            denied = evolve(service, keys=lambda _: evolve(envelope, keys=evolve(custody, client=denied_client)))
            with pytest.raises(NativeError, match="unavailable"):
                denied.read(access, record)
            write_private(policy_path, contracts.data(evolve(policy, grants={})))
            with pytest.raises(NativeError, match="unavailable"):
                service.read(access, record)
        with pytest.raises(NativeError, match="unavailable"):
            service.read(access, record)
