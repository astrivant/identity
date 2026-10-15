"""
Construct the production controller from reviewed configuration without importing broker server capabilities.
"""

from __future__ import annotations

import base64
import hashlib
import os
import resource
import time
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from agent_broker_sdk.client import CryptoClient
from agent_broker_sdk.exceptions import BrokerError
from attrs import evolve, frozen
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from psycopg import ProgrammingError
from psycopg.conninfo import conninfo_to_dict

from witful.collection.protection import require_protected
from witful.exceptions import NativeError, StorageProtectionError
from witful.native.api.admission import Admission
from witful.native.api.builder import Builder
from witful.native.authority import Access, Authority
from witful.native.broker import BrokerKeys
from witful.native.config import Backend, Settings, load, require_profile
from witful.native.context import Context
from witful.native.envelope import EnvelopeService, Signer
from witful.native.git import Git
from witful.native.postgres import Postgres
from witful.native.service import Service
from witful.native.storage import Scope

if TYPE_CHECKING:
    from flask import Flask

    from witful.native.storage import Store

__all__ = ["Runtime", "build", "create_app"]


@frozen
class MeteredKeys:
    """
    Observe actual broker calls without recording operations' inputs, grants or record labels.

    Attributes:
        keys (BrokerKeys): Released client adapter.
        admission (Admission): Local fixed-label metrics.
    """

    keys: BrokerKeys
    admission: Admission

    def invoke(self, action: Literal["wrap", "unwrap", "sign"], generation: str, context: Context, payload: bytes) -> bytes:
        """
        Measure the actual dependency boundary without altering retry or authorization semantics.

        Args:
            action (Literal["wrap", "unwrap", "sign"]): Cryptographic purpose.
            generation (str): Opaque key generation.
            context (Context): Expected immutable record binding.
            payload (bytes): Transient input, never retained by metrics.

        Returns:
            bytes: Actual broker output.
        """
        started = time.monotonic()
        try:
            return self.keys.invoke(action, generation, context, payload)
        finally:
            self.admission.observe("broker", time.monotonic() - started)


class Readiness:
    """
    Bound repeated dependency probes without turning their cached health observation into an access grant.
    """

    def __init__(self, settings: Settings, service: Service, admission: Admission, access: Access) -> None:
        """
        Inject actual production dependencies and a dedicated probe grant.

        Args:
            settings (Settings): Validated deployment settings.
            service (Service): Authenticated runtime.
            admission (Admission): Local metrics owner.
            access (Access): Independently provisioned probe identity and task.
        """
        self.settings = settings
        self.service = service
        self.admission = admission
        self.access = access
        self.lock = Lock()
        self.expires = 0.0
        self.result = False

    def __call__(self) -> bool:
        """
        Verify protection freshness on every call and serialize bounded external probes.

        Returns:
            bool: Last fresh successful dependency observation, never permission for another request.
        """
        try:
            self.service.protection()
        except NativeError:
            return False
        if not self.lock.acquire(blocking=False):
            return False
        try:
            if time.monotonic() < self.expires:
                return self.result
            self.result = False
            started = time.monotonic()
            registration = self.service.authority.check(self.access, "read", "*", int(time.time()))
            self.admission.observe("authority", time.monotonic() - started)
            started = time.monotonic()
            if self.service.store.head(self.access.scope) != registration.head:
                return False
            self.admission.observe("storage", time.monotonic() - started)
            # Probe custody without storing plaintext, a data key, or a synthetic record in the authoritative identity.
            context = Context(self.access.scope.tenant, self.access.scope.identity, str(uuid4()), 1)
            envelope = self.service.keys(self.access)
            sealed = envelope.seal(context, {"probe": 1})
            if envelope.open(context, sealed) != {"probe": 1}:
                return False
            self.service.authority.check(self.access, "read", "*", int(time.time()))
            self.result = True
            return True
        except NativeError:
            return False
        finally:
            self.expires = time.monotonic() + self.settings.runtime.readiness_seconds
            self.lock.release()


@frozen
class Runtime:
    """
    Own one constructed native application and its admission lifecycle.

    Attributes:
        application (Flask): Single consolidated application.
        service (Service): Native domain runtime.
        admission (Admission): Request owner stopped during graceful runtime shutdown.
    """

    application: Flask
    service: Service
    admission: Admission


def build(settings: Settings) -> Runtime:
    """
    Build the production runtime only after verifying current deployment evidence and transport separation.

    Args:
        settings (Settings): Closed operator-owned settings.

    Returns:
        Runtime: Complete service without launching a listener or creating keys, schemas or authorities.
    """
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    def protection() -> None:
        """
        Refuse expired or changed deployment evidence before native access.

        Returns:
            None: Current independent evidence authorizes this configured deployment boundary.
        """
        require_profile(settings, int(time.time()))

    protection()
    try:
        authority_url = os.environ["WITFUL_AUTHORITY_DATABASE_URL"]
        authority_options = conninfo_to_dict(authority_url)
        if authority_options.get("sslmode", "verify-full") != "verify-full":
            raise NativeError("denied")

        def storage(backend: Backend) -> Store:
            """
            Construct only an explicitly configured data boundary, without registering or migrating it.

            Args:
                backend (Backend): Selected source or inactive destination covered by signed deployment evidence.

            Returns:
                Store: Ciphertext adapter with verified transport and separation from the authority database.
            """
            if backend.kind == "postgres":
                database_url = os.environ[backend.database_environment]
                options = conninfo_to_dict(database_url)
                if options.get("sslmode", "verify-full") != "verify-full":
                    raise NativeError("denied")
                # Different credentials in the same database do not establish the independent control-plane boundary.
                if tuple(options.get(key) for key in ("host", "port", "dbname")) == tuple(
                    authority_options.get(key) for key in ("host", "port", "dbname")
                ):
                    raise NativeError("denied")
                return Postgres(database_url, backend.max_objects, backend.max_bytes, backend.synchronous)
            else:
                require_protected(Path(backend.path))
                return Git(Path(backend.path), backend.author, backend.email, backend.max_objects, backend.max_bytes)

        store = storage(settings.backend)
        targets = {backend.id: storage(backend) for backend in settings.destinations}
        broker = settings.broker
        client = CryptoClient(broker.url, Path(broker.ca), Path(broker.certificate), Path(broker.key))
        signers = {item.generation: Signer(base64.b64decode(item.public, validate=True), item.fingerprint) for item in broker.signers}
        certificate = x509.load_pem_x509_certificate(Path(settings.tls.client_certificate).read_bytes())
        fingerprint = hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest()
    except (KeyError, OSError, ValueError, ProgrammingError, BrokerError, StorageProtectionError):
        raise NativeError("unavailable") from None
    admission = Admission(settings.runtime.admission)

    def keys(access: Access) -> EnvelopeService:
        """
        Bind each key request to the admitted native grant and explicitly configured independent broker revisions.

        Args:
            access (Access): Current authorized request.

        Returns:
            EnvelopeService: Request-scoped cryptographic boundary containing no custodial private key.
        """
        protection()
        custody = MeteredKeys(BrokerKeys(client, access.grant, access.task, broker.authority, broker.policy), admission)
        return EnvelopeService(custody, broker.wrapping, broker.signing, signers)

    service = Service(store, Authority(authority_url, settings.backend.id), keys, protection, settings.budget)
    probe = settings.probe
    access = Access(Scope(probe.tenant, probe.identity), fingerprint, probe.grant, probe.task, probe.epoch, probe.policy)
    readiness = Readiness(settings, service, admission, access)
    destinations = tuple(
        evolve(service, store=target, authority=evolve(service.authority, backend=identifier)) for identifier, target in targets.items()
    )
    application = Builder(service, admission, readiness, destinations=destinations).build()
    application.extensions["witful.runtime"] = admission
    return Runtime(application, service, admission)


def create_app() -> Flask:
    """
    Load the explicitly selected runtime configuration for the production WSGI entrypoint.

    Returns:
        Flask: One protected, authenticated application.
    """
    location = os.environ.get("WITFUL_NATIVE_CONFIG")
    if not location:
        raise NativeError("invalid")
    return build(load(Path(location))).application
