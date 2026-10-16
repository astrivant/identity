"""
Expose authorized delivery, explicit completion and permit-only readiness preparation through the native controller application.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from attrs import evolve
from flask import Blueprint, Response

from witful.exceptions import NativeError
from witful.native import codec
from witful.native.api.requests import decode
from witful.native.context import Context, identifier
from witful.native.projection.intents import read
from witful.native.projection.models import PERMIT
from witful.native.projection.status import completion, status
from witful.native.projection.worker import deliver
from witful.native.wire import mapping, text

if TYPE_CHECKING:
    from collections.abc import Callable

    from witful.native.service import Service


def routes(service: Service, authenticate: Callable[[], str]) -> Blueprint:
    """
    Inject the source service without adding any remote Git credentials or listener to the controller.

    Args:
        service (Service): Configured native authority and protected storage.
        authenticate (Callable[[], str]): Actual mutual-TLS caller identity.

    Returns:
        Blueprint: Closed projection operations with current source authorization.
    """
    blueprint = Blueprint("native_projection_control", __name__)

    @blueprint.post("/v1/project-status")
    def inspect() -> Response:
        """
        Return complete authorized queue and last-verified frontier evidence without contacting a remote.

        Returns:
            Response: Bounded binary status for the caller's exact identity.
        """
        access, arguments = decode(service, authenticate)
        mapping(arguments, set())
        return Response(codec.encode(status(service, access), codec.Limits(bytes=service.budget.bytes)), mimetype="application/cbor")

    @blueprint.post("/v1/project-check")
    def check() -> Response:
        """
        Evaluate the original operation's retained remote requirement independently of local durability.

        Returns:
            Response: Explicit complete flag and pending/verified destination counts.
        """
        access, arguments = decode(service, authenticate)
        value = mapping(arguments, {"operation"})
        return Response(codec.encode(completion(service, access, text(value["operation"]))), mimetype="application/cbor")

    @blueprint.post("/v1/project-drain")
    def drain() -> Response:
        """
        Attempt one ordered candidate when explicitly requested or when its configured scheduling threshold is due.

        Returns:
            Response: Independent remote outcome or an explicit scheduling state; no hidden unbounded retry loop.
        """
        access, arguments = decode(service, authenticate)
        value = mapping(arguments, {"target", "scheduled"})
        target, scheduled = identifier(text(value["target"])), value["scheduled"]
        if type(scheduled) is not bool:
            raise NativeError("invalid")
        started = service.monotonic()
        registration, frontier = service.snapshot(access, "project", "*")
        pending = [read(service, access, pointer) for pointer in frontier.outbox]
        selected = [intent for intent in pending if intent.target.id == target]
        state = "ready" if selected else "idle"
        policy = service.projection
        if scheduled and selected:
            age = max(0, int(service.clock()) - selected[0].recorded)
            if policy.mode in {"disabled", "manual"}:
                state = policy.mode
            elif policy.mode == "interval" and age < policy.interval_seconds:
                state = "waiting"
            elif policy.mode == "batch" and len(selected) < policy.batch_size and age < policy.interval_seconds:
                state = "waiting"
        service.release(access, "project", "*", registration, started)
        result = deliver(service, access, target, policy.author, policy.email) if state == "ready" else {"state": state, "target": target}
        return Response(codec.encode(result), mimetype="application/cbor")

    @blueprint.post("/v1/project-probe")
    def probe() -> Response:
        """
        Seal an explicitly requested kind-18 readiness probe without creating identity history or granting gateway signing authority.

        Returns:
            Response: Signed encrypted probe and opaque context for the separately configured gateway's readiness mount.
        """
        access, arguments = decode(service, authenticate)
        mapping(arguments, set())
        started = service.monotonic()
        registration, _ = service.snapshot(access, "project", "*")
        context = Context(access.scope.tenant, access.scope.identity, str(uuid4()), PERMIT)
        wrapping = identifier(service.projection.permit_wrapping)
        keys = service.keys(access)
        if wrapping == keys.wrapping:
            raise NativeError("denied")
        sealed = evolve(keys, wrapping=wrapping).seal(context, {"probe": 1})
        service.release(access, "project", "*", registration, started)
        return Response(codec.encode({"context": context.data(), "sealed": sealed}), mimetype="application/cbor")

    return blueprint
