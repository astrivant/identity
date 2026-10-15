"""
Load closed native-controller configuration and independently signed deployment protection evidence.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Literal

from attrs import frozen
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native import codec
from witful.native.context import identifier
from witful.native.models import parse
from witful.native.service import Budget
from witful.native.values import pack

__all__ = ["Settings", "load", "require_profile"]


@frozen
class Trust:
    """
    Pin an independently approved broker verification key.

    Attributes:
        generation (str): Opaque signing-generation UUID.
        public (str): Base64 DER Ed25519 public key.
        fingerprint (str): Independently trusted SHA-256 of the DER bytes.
    """

    generation: str
    public: str
    fingerprint: str


@frozen
class Broker:
    """
    Configure the lightweight client for an independently deployed key broker.

    Attributes:
        url (str): HTTPS broker origin.
        ca (str): Trusted broker CA path.
        certificate (str): Controller client certificate path.
        key (str): Controller client key path; no custodial wrapping or signing key is installed here.
        wrapping (str): Wrapping generation for new envelopes.
        signing (str): Signing generation for new envelopes.
        authority (str): Broker authority revision UUID, separately provisioned from the native backend epoch.
        policy (str): Broker key policy revision UUID.
        signers (tuple[Trust, ...]): Independently pinned historical signing generations.
    """

    url: str
    ca: str
    certificate: str
    key: str
    wrapping: str
    signing: str
    authority: str
    policy: str
    signers: tuple[Trust, ...]


@frozen
class TLS:
    """
    Configure mandatory mutual TLS for the single native application listener.

    Attributes:
        certificate (str): Server certificate path.
        key (str): Server private key path.
        ca (str): Trusted client CA path.
        server_name (str): Certificate name used by local authenticated readiness probes.
        client_certificate (str): Local probe client certificate path.
        client_key (str): Local probe client key path.
    """

    certificate: str
    key: str
    ca: str
    server_name: str
    client_certificate: str
    client_key: str


@frozen
class Backend:
    """
    Bind configured storage to an existing independent authority registration.

    Attributes:
        id (str): Registered opaque storage-instance UUID.
        database_environment (str): Existing environment variable containing this backend's database URL.
        kind (Literal["postgres", "git"]): Explicit selected adapter, never an implicit migration request.
        path (str): Existing protected bare repository for Git mode.
        author (str): Honest exporter attribution for new native Git commits.
        email (str): Exporter contact for newly generated commits.
        synchronous (bool): Require PostgreSQL remote_apply and configured synchronous standby policy.
        max_objects (int): Aggregate persistence object/history budget.
        max_bytes (int): Aggregate ciphertext transfer budget.
    """

    id: str
    database_environment: str = "WITFUL_DATABASE_URL"
    kind: Literal["postgres", "git"] = "postgres"
    path: str = ""
    author: str = "Witful controller"
    email: str = "controller@example.invalid"
    synchronous: bool = False
    max_objects: int = 4096
    max_bytes: int = 64 * 1024 * 1024


@frozen
class Runtime:
    """
    Surface the owned server's concurrency and termination controls without arbitrary worker ceilings.

    Attributes:
        host (str): Private listener binding.
        port (int): TLS listener port.
        workers (int): Independent Gunicorn worker processes.
        threads (int): Threads per worker.
        worker_connections (int): Maximum simultaneous Gunicorn connections per worker, including idle keepalive sockets.
        backlog (int): Kernel socket backlog, separate from the application queue.
        admission (int): Maximum actively owned requests per worker.
        timeout (int): Gunicorn worker timeout seconds.
        graceful_timeout (int): Maximum worker drain seconds before runtime termination.
        keepalive (int): Idle keepalive seconds.
        working_directory (str): Existing protected directory for owned runtime files and temporary recovery work.
        readiness_seconds (int): Minimum interval between key/dependency readiness probes.
    """

    host: str = "0.0.0.0"
    port: int = 8443
    workers: int = 1
    threads: int = 4
    worker_connections: int = 64
    backlog: int = 128
    admission: int = 4
    timeout: int = 60
    graceful_timeout: int = 30
    keepalive: int = 2
    working_directory: str = "/run/witful"
    readiness_seconds: int = 30


@frozen
class Probe:
    """
    Select an explicitly provisioned non-user request for readiness verification.

    Attributes:
        tenant (str): Opaque test scope within the deployment.
        identity (str): Opaque readiness identity scope.
        grant (str): Native and broker readiness grant UUID.
        task (str): Explicit readiness task UUID.
        epoch (int): Expected current backend epoch.
        policy (str): Native authority policy revision UUID.
    """

    tenant: str
    identity: str
    grant: str
    task: str
    epoch: int
    policy: str


@frozen
class Protection:
    """
    Pin separately administered, expiring deployment evidence rather than treating TLS as disk attestation.

    Attributes:
        path (str): Signed evidence package path.
        public (str): Base64 raw Ed25519 verification key, provisioned independently of the package.
        fingerprint (str): Independently trusted SHA-256 of raw public key bytes.
    """

    path: str
    public: str
    fingerprint: str


@frozen
class ArchivePath:
    """
    Bind an operator-reviewed original Git filesystem location to exactly one identity and direction.

    Attributes:
        name (str): Request-facing nonempty alias, never an arbitrary client path.
        tenant (str): Admitted opaque tenant UUID.
        identity (str): Admitted opaque identity UUID.
        path (str): Absolute protected source Git directory or absent restore destination.
        mode (Literal["capture", "restore"]): Independently configured filesystem effect.
    """

    name: str
    tenant: str
    identity: str
    path: str
    mode: Literal["capture", "restore"]


@frozen
class ExportRecipient:
    """
    Bind a reviewed public export recipient to one identity instead of accepting arbitrary request keys.

    Attributes:
        name (str): Unique request-facing recipient alias.
        tenant (str): Opaque admitted tenant UUID.
        identity (str): Opaque admitted identity UUID.
        generation (str): Recipient wrapping-generation UUID.
        public (str): Base64 DER RSA public key; private recipient keys never enter controller configuration.
        fingerprint (str): Independently reviewed SHA-256 of the public DER bytes.
    """

    name: str
    tenant: str
    identity: str
    generation: str
    public: str
    fingerprint: str


@frozen
class Settings:
    """
    Compose the complete deployment-owned configuration; credentials are read from existing authoritative environment names.

    Attributes:
        backend (Backend): Existing selected backend.
        tls (TLS): Native listener and probe transport.
        broker (Broker): Independent key-custody client.
        probe (Probe): Dedicated readiness grant.
        protection (Protection): Independently signed protection evidence.
        runtime (Runtime): Server lifecycle and concurrency controls.
        budget (Budget): Explicit native operation limits.
        destinations (tuple[Backend, ...]): Explicit inactive migration targets covered by the same signed deployment evidence.
        archives (tuple[ArchivePath, ...]): Identity-bound original Git source/restore locations, empty by default.
        recipients (tuple[ExportRecipient, ...]): Explicit identity-bound public sharing recipients, empty by default.
        envelope (codec.Limits): Per-record binary payload and structural bounds, including explicit full-history package capacity.
        version (Literal[1]): Configuration schema version.
    """

    backend: Backend
    tls: TLS
    broker: Broker
    probe: Probe
    protection: Protection
    runtime: Runtime = Runtime()
    budget: Budget = Budget()
    destinations: tuple[Backend, ...] = ()
    archives: tuple[ArchivePath, ...] = ()
    recipients: tuple[ExportRecipient, ...] = ()
    envelope: codec.Limits = codec.DEFAULT_LIMITS
    version: Literal[1] = 1


@frozen
class Evidence:
    """
    Describe a separately reviewed deployment's current protection controls without claiming their signature is a hardware attestation.

    Attributes:
        configuration (str): Digest of the exact effective non-secret Settings object.
        issued (int): UTC epoch seconds of the evidence observation.
        expires (int): Exclusive expiration requiring renewed verification.
        controls (tuple[str, ...]): Complete required reviewed controls.
        references (tuple[str, ...]): Operator-owned evidence references, without credentials or private payloads.
        version (Literal[1]): Evidence contract version.
    """

    configuration: str
    issued: int
    expires: int
    controls: tuple[str, ...]
    references: tuple[str, ...]
    version: Literal[1] = 1


def load(path: Path) -> Settings:
    """
    Load and validate a bounded closed configuration without printing rejected content.

    Args:
        path (Path): Operator-owned JSON configuration.

    Returns:
        Settings: Validated immutable configuration; deployment evidence is verified separately on each admission boundary.
    """
    try:
        with path.open("rb") as stream:
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise NativeError("invalid")
        settings = parse(json.loads(data), Settings)
    except (OSError, ValueError):
        raise NativeError("invalid") from None
    backends = (settings.backend, *settings.destinations)
    if len({backend.id for backend in backends}) != len(backends):
        raise NativeError("invalid")
    for backend in backends:
        identifier(backend.id)
        if backend.max_objects < 1 or backend.max_bytes < 1 or not backend.database_environment.isidentifier():
            raise NativeError("invalid")
    for value in (
        settings.broker.wrapping,
        settings.broker.signing,
        settings.broker.authority,
        settings.broker.policy,
        settings.probe.tenant,
        settings.probe.identity,
        settings.probe.grant,
        settings.probe.task,
        settings.probe.policy,
    ):
        identifier(value)
    if len({archive.name for archive in settings.archives}) != len(settings.archives):
        raise NativeError("invalid")
    for archive in settings.archives:
        identifier(archive.tenant)
        identifier(archive.identity)
        if not archive.name or not Path(archive.path).is_absolute():
            raise NativeError("invalid")
    from witful.native.sharing import Recipient

    if len({recipient.name for recipient in settings.recipients}) != len(settings.recipients):
        raise NativeError("invalid")
    for recipient in settings.recipients:
        identifier(recipient.tenant)
        identifier(recipient.identity)
        if not recipient.name:
            raise NativeError("invalid")
        try:
            Recipient(recipient.generation, base64.b64decode(recipient.public, validate=True), recipient.fingerprint).key()
        except ValueError:
            raise NativeError("invalid") from None
    runtime = settings.runtime
    if any(
        value < 1
        for value in (
            runtime.port,
            runtime.workers,
            runtime.threads,
            runtime.backlog,
            runtime.worker_connections,
            runtime.admission,
            runtime.timeout,
            runtime.graceful_timeout,
            runtime.keepalive,
            runtime.readiness_seconds,
            settings.backend.max_objects,
            settings.backend.max_bytes,
            settings.probe.epoch,
        )
    ):
        raise NativeError("invalid")
    if not Path(runtime.working_directory).is_absolute():
        raise NativeError("invalid")
    if runtime.port > 65535 or runtime.timeout < runtime.graceful_timeout or runtime.worker_connections < runtime.threads:
        raise NativeError("invalid")
    if not settings.broker.signers or len({item.generation for item in settings.broker.signers}) != len(settings.broker.signers):
        raise NativeError("invalid")
    for signer in settings.broker.signers:
        identifier(signer.generation)
    if any(backend.kind == "git" and (not backend.path or runtime.workers != 1) for backend in backends):
        raise NativeError("invalid")
    return settings


def require_profile(settings: Settings, now: int) -> Evidence:
    """
    Verify an independent, expiring protection decision bound to this exact deployed configuration.

    Args:
        settings (Settings): Effective operator-owned settings.
        now (int): Current trusted UTC epoch time.

    Returns:
        Evidence: Authenticated reviewed controls; this is not proof against a compromised attester or host.
    """
    from witful.native.wire import binary, mapping

    try:
        with Path(settings.protection.path).open("rb") as stream:
            encoded = stream.read(1024 * 1024 + 1)
        package = mapping(codec.decode(encoded, codec.Limits(bytes=1024 * 1024)), {"payload", "signature"})
        public = base64.b64decode(settings.protection.public, validate=True)
        if hashlib.sha256(public).hexdigest() != settings.protection.fingerprint:
            raise NativeError("denied")
        payload = binary(package["payload"])
        Ed25519PublicKey.from_public_bytes(public).verify(binary(package["signature"]), b"witful-storage-evidence-v1\0" + payload)
        evidence = parse(codec.decode(payload), Evidence)
    except (OSError, ValueError, InvalidSignature):
        raise NativeError("denied") from None
    required = {
        "data-volume-encryption",
        "authority-volume-encryption",
        "wal-and-backup-encryption",
        "temp-memory-noswap",
        "core-dumps-disabled",
        "tls",
        "role-separation",
        "old-primary-fencing",
        "recovery-tested",
    }
    if evidence.configuration != hashlib.sha256(codec.encode(pack(as_data(settings)))).hexdigest():
        raise NativeError("conflict")
    if not evidence.issued <= now < evidence.expires or set(evidence.controls) != required or not evidence.references:
        raise NativeError("denied")
    if any(not value.strip() for value in evidence.references) or len(evidence.controls) != len(required):
        raise NativeError("invalid")
    return evidence
