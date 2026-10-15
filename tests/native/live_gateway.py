"""
Compose a real isolated gateway for transport tests, substituting only deployment attestation with an explicit synthetic boundary.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from agent_broker_sdk.client import CryptoClient
from witful.native.api.admission import Admission
from witful.native.authority import Authority
from witful.native.broker import BrokerKeys
from witful.native.config import load
from witful.native.envelope import EnvelopeService, Signer
from witful.native.projection.gateway import Builder, Destination, Gateway
from witful.native.projection.transport import GitRemote
from witful.native.storage import Scope
from witful.native.wire import mapping, text

if TYPE_CHECKING:
    from flask import Flask


def create_app() -> Flask:
    """
    Load synthetic references without native data-store credentials, retaining actual mTLS, broker, grant and SSH boundaries.

    Returns:
        Flask: One gateway application with a real released broker client and independently administered authority.
    """
    settings = load(Path(os.environ["WITFUL_NATIVE_CONFIG"]))
    factory = mapping(
        json.loads(Path(os.environ["WITFUL_TEST_GATEWAY_FACTORY"]).read_text()), {"authority", "target", "url", "environment"}
    )
    broker = settings.broker
    client = CryptoClient(broker.url, Path(broker.ca), Path(broker.certificate), Path(broker.key))
    custody = BrokerKeys(client, settings.probe.grant, settings.probe.task, broker.authority, broker.policy)
    signers = {item.generation: Signer(base64.b64decode(item.public), item.fingerprint) for item in broker.signers}
    keys = EnvelopeService(custody, broker.wrapping, broker.signing, signers)
    environment = factory["environment"]
    assert isinstance(environment, dict)
    remote = GitRemote(Path(settings.runtime.working_directory), text(factory["url"]), "refs/heads/projection", environment)
    target = Destination(
        text(factory["target"]),
        Scope(settings.probe.tenant, settings.probe.identity),
        remote,
        "Synthetic Export",
        "fixture@example.invalid",
    )
    gateway = Gateway(Authority(text(factory["authority"]), settings.backend.id), (target,), lambda _: keys, lambda: None, settings.budget)
    admission = Admission(2)
    application = Builder(gateway, admission, lambda: True).build()
    application.extensions["witful.runtime"] = admission
    return application
