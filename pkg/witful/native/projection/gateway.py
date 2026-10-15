"""
Isolate remote Git credentials behind current native authorization and a narrowly scoped encrypted publication permit.
"""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from attrs import field, frozen
from flask import Blueprint, Response

from witful.exceptions import NativeError
from witful.native import codec
from witful.native.api.builder import Boundary, peer_fingerprint
from witful.native.api.requests import decode_request
from witful.native.context import Context, identifier
from witful.native.kinds import BACKUP
from witful.native.models import parse
from witful.native.projection.bundle import Bundle, validate
from witful.native.projection.models import PERMIT, Permit
from witful.native.wire import binary, mapping, text

if TYPE_CHECKING:
    from collections.abc import Callable

    from flask import Flask

    from witful.native.api.admission import Admission
    from witful.native.authority import Access, Authority
    from witful.native.envelope import EnvelopeService
    from witful.native.projection.transport import GitRemote
    from witful.native.service import Budget
    from witful.native.storage import Scope


@frozen
class Destination:
    """
    Resolve an opaque destination to operator-owned remote credentials and approved attribution.

    Attributes:
        id (str): Stable opaque destination UUID.
        scope (Scope): Exact authorized tenant and identity.
        remote (GitRemote): Sole-writer remote transport configured independently of request data.
        author (str): Approved honest export author.
        email (str): Approved export contact.
    """

    id: str
    scope: Scope
    remote: GitRemote
    author: str
    email: str


@frozen
class Gateway:
    """
    Authorize and verify encrypted delivery while possessing neither domain decryption grants nor native data-store credentials.

    Attributes:
        authority (Authority): Independently administered current native grants and backend epoch.
        targets (tuple[Destination, ...]): Operator-owned remote allowlist.
        keys (Callable[[Access], EnvelopeService]): Permit-only unwrap grant and independent public archive signer pins.
        protection (Callable[[], None]): Verified private working-storage boundary.
        budget (Budget): Bounded request and cryptographic processing.
        clock (Callable[[], float]): Explicit UTC clock for current authorization.
    """

    authority: Authority
    targets: tuple[Destination, ...]
    keys: Callable[[Access], EnvelopeService] = field(repr=False)
    protection: Callable[[], None] = field(repr=False)
    budget: Budget
    clock: Callable[[], float] = time.time

    def authorize(self, access: Access, permit: Permit) -> None:
        """
        Require current delegate and original writer permissions before effect and result release, without retaining a database lock.

        Args:
            access (Access): Actual mTLS delegate identity and independently provisioned task/grant.
            permit (Permit): Authenticated original accepted source and candidate bindings.

        Returns:
            None: Destination delegation, original disclosure authority and backend epoch are current.
        """
        intent = permit.intent
        if (
            access.scope != intent.access.scope
            or access.grant != intent.target.grant
            or access.task != intent.target.task
            or (access.epoch, access.policy) != (intent.access.epoch, intent.access.policy)
        ):
            raise NativeError("denied")
        now = int(self.clock())
        registration = self.authority.check(access, "project", "*", now)
        if intent.backend != registration.backend or intent.generation > registration.head.generation:
            raise NativeError("conflict")
        for action in ("project", "export"):
            if self.authority.check(intent.access, action, "*", now) != registration:
                raise NativeError("conflict")

    def deliver(self, access: Access, target: str, operation: str, envelope: bytes, raw: bytes) -> dict[str, object]:
        """
        Admit exactly one signed candidate and acknowledge it only after independent remote object readback.

        Args:
            access (Access): Authenticated controller-to-gateway access, never a caller-selected subject.
            target (str): Opaque destination from the configured allowlist.
            operation (str): Original accepted native operation UUID.
            envelope (bytes): Exact signed encrypted permit bytes, separately authorized for gateway decryption.
            raw (bytes): Exact prepared Git objects containing only encrypted native history and approved export metadata.

        Returns:
            dict[str, object]: Bounded remote verification receipt over authenticated transport; local durability remains separate.
        """
        started = time.monotonic()
        self.protection()
        identifier(operation)
        destination = next((item for item in self.targets if item.id == target and item.scope == access.scope), None)
        if destination is None:
            raise NativeError("denied")
        self.authority.check(access, "project", "*", int(self.clock()))
        record = str(uuid5(UUID(operation), identifier(target)))
        context = Context(access.scope.tenant, access.scope.identity, str(uuid5(UUID(record), "permit")), PERMIT)
        keys = self.keys(access)
        permit = parse(keys.open(context, envelope), Permit)
        if (
            permit.intent.operation != operation
            or permit.intent.target.id != target
            or permit.context != Context(access.scope.tenant, access.scope.identity, record, BACKUP)
            or (permit.author, permit.email) != (destination.author, destination.email)
            or permit.digest != hashlib.sha256(raw).hexdigest()
        ):
            raise NativeError("invalid")
        bundle = Bundle.decode(raw, codec.Limits(bytes=self.budget.bytes))
        validate(bundle, record, permit.expected, permit.author, permit.email, permit.recorded)
        if bundle.objects()[-1][1] != permit.oid:
            raise NativeError("invalid")
        # Public signature verification requires no archive unwrap capability at the gateway.
        keys.verify(permit.context, bundle.blob)
        with destination.remote.lock() as descriptor:
            self.protection()
            self.authorize(access, permit)
            oid = destination.remote.publish(bundle, permit.expected, descriptor, started + self.budget.seconds)
            self.authorize(access, permit)
        self.protection()
        return {
            "state": "remote_verified",
            "operation": operation,
            "target": target,
            "generation": permit.intent.generation,
            "oid": oid,
        }


@frozen
class Builder:
    """
    Compose the isolated delivery role into the same single-app authentication, metrics and lifecycle pattern as the controller.

    Attributes:
        gateway (Gateway): Credential-isolated delivery service.
        admission (Admission): Bounded local work ownership.
        readiness (Callable[[], bool]): Bounded current configuration, authority and key-readiness probe.
        authenticate (Callable[[], str]): Actual verified mutual-TLS socket boundary.
    """

    gateway: Gateway
    admission: Admission
    readiness: Callable[[], bool]
    authenticate: Callable[[], str] = peer_fingerprint

    def build(self) -> Flask:
        """
        Register the delivery endpoint and private operations on one Flask application.

        Returns:
            Flask: Complete gateway app; the runtime owns listeners and shutdown.
        """
        blueprint = Blueprint("native_projection", __name__)

        @blueprint.post("/v1/project-deliver")
        def deliver() -> Response:
            """
            Decode a closed authenticated request and delegate publication without exposing provider diagnostics.

            Returns:
                Response: Current independently verified remote receipt or centrally bounded error.
            """
            access, arguments = decode_request(self.authenticate, self.gateway.protection, self.gateway.budget.bytes)
            value = mapping(arguments, {"target", "operation", "permit", "bundle"})
            result = self.gateway.deliver(
                access, text(value["target"]), text(value["operation"]), binary(value["permit"]), binary(value["bundle"])
            )
            return Response(codec.encode(result), mimetype="application/cbor")

        return Boundary("witful.projection", self.gateway.budget.bytes, self.admission, self.readiness, (blueprint,)).build()
