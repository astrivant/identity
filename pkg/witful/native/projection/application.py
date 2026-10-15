"""
Build the independently deployed projection gateway without opening native data storage or receiving domain decryption authority.
"""

from __future__ import annotations

import base64
import hashlib
import os
import resource
import shlex
import time
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from agent_broker_sdk.client import CryptoClient
from agent_broker_sdk.exceptions import BrokerError
from attrs import frozen
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from psycopg.conninfo import conninfo_to_dict

from witful.collection.protection import require_protected
from witful.exceptions import NativeError, StorageProtectionError
from witful.native import codec
from witful.native.api.admission import Admission
from witful.native.application import MeteredKeys
from witful.native.authority import Access, Authority
from witful.native.broker import BrokerKeys
from witful.native.config import require_profile
from witful.native.context import Context
from witful.native.envelope import EnvelopeService, Signer
from witful.native.models import parse
from witful.native.projection.gateway import Builder, Destination, Gateway
from witful.native.projection.models import PERMIT
from witful.native.projection.transport import GitRemote
from witful.native.storage import Scope
from witful.native.wire import binary, mapping

if TYPE_CHECKING:
    from flask import Flask

    from witful.native.config import Settings


class Readiness:
    """
    Test current permit-only key access using an operator-retained signed encrypted probe and bounded serialized health observations.
    """

    def __init__(self, settings: Settings, gateway: Gateway, admission: Admission, access: Access) -> None:
        """
        Bind the explicit probe grant and existing ciphertext probe to this isolated runtime.

        Args:
            settings (Settings): Complete signed deployment settings.
            gateway (Gateway): Credential-isolated application service.
            admission (Admission): Local metrics and lifecycle owner.
            access (Access): Actual probe certificate fingerprint and provisioned task/grant.
        """
        self.settings = settings
        self.gateway = gateway
        self.admission = admission
        self.access = access
        self.lock = Lock()
        self.expires = 0.0
        self.result = False

    def __call__(self) -> bool:
        """
        Verify current native projection policy, configured signer/wrapping generations and real permit unwrapping without remote Git I/O.

        Returns:
            bool: Fresh dependency readiness; remote outage does not control liveness.
        """
        try:
            self.gateway.protection()
        except NativeError:
            return False
        if not self.lock.acquire(blocking=False):
            return False
        try:
            if time.monotonic() < self.expires:
                return self.result
            self.result = False
            started = time.monotonic()
            self.gateway.authority.check(self.access, "project", "*", int(time.time()))
            self.admission.observe("authority", time.monotonic() - started)
            with Path(self.settings.probe.envelope).open("rb") as stream:
                raw = stream.read(self.settings.envelope.bytes + 1)
            value = mapping(codec.decode(raw, self.settings.envelope), {"context", "sealed"})
            context = parse(value["context"], Context)
            if (context.tenant, context.identity, context.kind) != (self.access.scope.tenant, self.access.scope.identity, PERMIT):
                return False
            keys = self.gateway.keys(self.access)
            envelope = binary(value["sealed"])
            header = keys.verify(context, envelope)
            if header["w"] != keys.wrapping or header["s"] != keys.signing or keys.open(context, envelope) != {"probe": 1}:
                return False
            self.gateway.authority.check(self.access, "project", "*", int(time.time()))
            self.result = True
            return True
        except (NativeError, OSError):
            return False
        finally:
            self.expires = time.monotonic() + self.settings.runtime.readiness_seconds
            self.lock.release()


@frozen
class Runtime:
    """
    Own one isolated gateway app without a native data-store handle.

    Attributes:
        application (Flask): Consolidated mutually authenticated service and operational endpoints.
        gateway (Gateway): Remote publication boundary.
        admission (Admission): Request ownership and shutdown state.
    """

    application: Flask
    gateway: Gateway
    admission: Admission


def build(settings: Settings) -> Runtime:
    """
    Construct the configured isolated role from independent authority credentials and mounted repository-scoped SSH material.

    Args:
        settings (Settings): Validated projection-role configuration, covered by current signed protection evidence.

    Returns:
        Runtime: Complete app without native storage access, credential provisioning or remote publication during startup.
    """
    if settings.role != "projection":
        raise NativeError("invalid")
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    def protection() -> None:
        """
        Revalidate the independently signed deployment evidence before key use and every admitted request.

        Returns:
            None: Current signed profile remains valid.
        """
        require_profile(settings, int(time.time()))

    protection()
    admission = Admission(settings.runtime.admission)
    try:
        require_protected(Path(settings.runtime.working_directory))
        authority_url = os.environ["WITFUL_AUTHORITY_DATABASE_URL"]
        if conninfo_to_dict(authority_url).get("sslmode", "verify-full") != "verify-full":
            raise NativeError("denied")
        broker = settings.broker
        client = CryptoClient(broker.url, Path(broker.ca), Path(broker.certificate), Path(broker.key))
        signers = {item.generation: Signer(base64.b64decode(item.public, validate=True), item.fingerprint) for item in broker.signers}
        certificate = x509.load_pem_x509_certificate(Path(settings.tls.client_certificate).read_bytes())
        fingerprint = hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest()
        destinations: list[Destination] = []
        for target in settings.gateway:
            path = Path(target.directory)
            path.mkdir(mode=0o700, parents=False, exist_ok=True)
            require_protected(path)
            if not Path(target.ssh_key).is_file() or not Path(target.known_hosts).is_file():
                raise NativeError("unavailable")
            command = shlex.join(
                (
                    "ssh",
                    "-F",
                    "/dev/null",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "IdentitiesOnly=yes",
                    "-o",
                    "IdentityAgent=none",
                    "-o",
                    "StrictHostKeyChecking=yes",
                    "-o",
                    f"UserKnownHostsFile={target.known_hosts}",
                    "-i",
                    target.ssh_key,
                )
            )
            environment = {
                "GIT_SSH_COMMAND": command,
                "GIT_CONFIG_COUNT": "2",
                "GIT_CONFIG_KEY_0": "protocol.allow",
                "GIT_CONFIG_VALUE_0": "never",
                "GIT_CONFIG_KEY_1": "protocol.ssh.allow",
                "GIT_CONFIG_VALUE_1": "always",
            }
            remote = GitRemote(path, target.url, target.ref, environment, settings.budget.bytes)
            destinations.append(Destination(target.id, Scope(target.tenant, target.identity), remote, target.author, target.email))
    except (KeyError, OSError, ValueError, BrokerError, StorageProtectionError):
        raise NativeError("unavailable") from None

    def keys(access: Access) -> EnvelopeService:
        """
        Bind each permit unwrap to its current explicit grant without adding signing or domain-decryption capability.

        Args:
            access (Access): Current actual caller or independently configured readiness probe.

        Returns:
            EnvelopeService: Public verifier and independently enforced permit-only broker client.
        """
        protection()
        custody = MeteredKeys(BrokerKeys(client, access.grant, access.task, broker.authority, broker.policy), admission)
        return EnvelopeService(custody, broker.wrapping, broker.signing, signers, settings.envelope)

    gateway = Gateway(Authority(authority_url, settings.backend.id), tuple(destinations), keys, protection, settings.budget)
    probe = settings.probe
    access = Access(Scope(probe.tenant, probe.identity), fingerprint, probe.grant, probe.task, probe.epoch, probe.policy)
    application = Builder(gateway, admission, Readiness(settings, gateway, admission, access)).build()
    application.extensions["witful.runtime"] = admission
    return Runtime(application, gateway, admission)
