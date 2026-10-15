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
from witful.knowledge.contracts import as_data
from witful.native.broker import BrokerKeys
from witful.native.config import Broker, Trust
from witful.native.context import Context
from witful.native.projection.models import PERMIT
from witful.native.projection.preparation import load, prepare

from tests.native.gateway_transport import exercise
from tests.native.projection import configured
from tests.native.runtime import lesson

if TYPE_CHECKING:
    from pathlib import Path

    from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

    from tests.native.conftest import Fixture
    from tests.native.database import Databases
    from tests.native.runtime import Runtime


def test_native_records_use_released_sdk_over_mtls(runtime: Runtime, fixture: Fixture, tmp_path: Path, databases: Databases) -> None:
    """
    Require an enrolled certificate and current broker grant for actual native writes and reads through the released SDK.

    Args:
        runtime (Runtime): Real native data/control boundary with synthetic grants.
        fixture (Fixture): Independently held synthetic cryptographic keys and verification pins.
        tmp_path (Path): Disposable synthetic policy and certificate workspace.
        databases (Databases): Test-only native grant administrator.

    Returns:
        None: Real service/client TLS round trips preserve records; certificate substitution, revocation and outage fail closed.
    """
    root = tmp_path / "broker"
    root.mkdir()
    access = runtime.access
    base = configured(runtime, databases)
    permit_generation = base.projection.permit_wrapping
    authority, policy_revision = str(uuid4()), str(uuid4())
    keys: dict[str, rsa.RSAPrivateKey | ed25519.Ed25519PrivateKey] = {**fixture.keys.wrapping, **fixture.keys.signing}
    secrets = {
        "op://synthetic/" + generation + "/key": base64.b64encode(
            key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        ).decode()
        for generation, key in keys.items()
    }
    configured_keys = {
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
        target = base.projection.targets[0]
        gateway_grant = target.grant
        gateway_fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert((root / "bravo.pem").read_text())).hexdigest()
        permit_grant = evolve(
            grant, certificate_sha256=gateway_fingerprint, task=target.task, actions=("unwrap",), keys=(permit_generation,)
        )
        policy = Policy(configured_keys, {access.grant: grant, gateway_grant: permit_grant})
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
            service = evolve(base, keys=lambda _: envelope)
            service.append(access, str(uuid4()), "main", None, (lesson(),))
            record = service.history(access, "main")[0][0].id
            assert service.read(access, record) == lesson()
            _, prepared = prepare(service, access, service.projection.targets[0].id, "Synthetic Export", "fixture@example.invalid")
            bundle, permit, raw_permit = load(service, access, prepared)
            gateway_client = CryptoClient(url, root / "ca.pem", root / "bravo.pem", root / "bravo.key")
            gateway_custody = BrokerKeys(gateway_client, gateway_grant, target.task, authority, policy_revision)
            gateway_keys = evolve(envelope, keys=gateway_custody, wrapping=permit_generation)
            context = Context(access.scope.tenant, access.scope.identity, prepared.permit.record, PERMIT)
            assert gateway_keys.open(context, raw_permit) == as_data(permit)
            # These denials come from the released broker and maintained policy evaluator, not a test-only kind guard.
            with pytest.raises(NativeError, match="unavailable"):
                gateway_keys.open(permit.context, bundle.blob)
            with pytest.raises(NativeError, match="unavailable"):
                gateway_custody.invoke("sign", envelope.signing, context, b"0" * 32)
            with pytest.raises(NativeError, match="unavailable"):
                gateway_keys.seal(context, {"probe": 1})
            broker = Broker(
                url=url,
                ca=str(root / "ca.pem"),
                certificate=str(root / "bravo.pem"),
                key=str(root / "bravo.key"),
                wrapping=permit_generation,
                signing=envelope.signing,
                authority=authority,
                policy=policy_revision,
                signers=tuple(
                    Trust(generation, base64.b64encode(signer.public).decode(), signer.fingerprint)
                    for generation, signer in envelope.signers.items()
                ),
            )
            exercise(service, access, databases, root, broker)
            denied_client = CryptoClient(url, root / "ca.pem", root / "bravo.pem", root / "bravo.key")
            denied = evolve(service, keys=lambda _: evolve(envelope, keys=evolve(custody, client=denied_client)))
            with pytest.raises(NativeError, match="unavailable"):
                denied.read(access, record)
            write_private(policy_path, contracts.data(evolve(policy, grants={})))
            with pytest.raises(NativeError, match="unavailable"):
                service.read(access, record)
        with pytest.raises(NativeError, match="unavailable"):
            service.read(access, record)
