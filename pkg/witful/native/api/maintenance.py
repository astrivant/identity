"""
Expose explicit recovery and key-lifecycle operations through the same authenticated application.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Literal

from flask import Blueprint, Response

from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native import codec
from witful.native.api.requests import decode
from witful.native.backup import archive, restore
from witful.native.context import Context
from witful.native.migration import abort, migrate
from witful.native.models import parse
from witful.native.rotation import rotate
from witful.native.wire import binary, mapping, text

if TYPE_CHECKING:
    from collections.abc import Callable

    from witful.native.service import Service


def routes(service: Service, authenticate: Callable[[], str], destinations: tuple[Service, ...]) -> Blueprint:
    """
    Register explicit lifecycle operations without accepting arbitrary endpoints, paths or credentials from a request.

    Args:
        service (Service): Current controller-owned protected service.
        authenticate (Callable[[], str]): Verified mutual TLS peer boundary.
        destinations (tuple[Service, ...]): Independently reviewed inactive targets from deployment configuration.

    Returns:
        Blueprint: Maintenance routes behind the same central authentication, admission and error boundaries.
    """
    blueprint = Blueprint("native_maintenance", __name__)
    targets = {target.authority.backend: target for target in destinations}

    def respond(value: object) -> Response:
        """
        Bound a successful authenticated lifecycle response.

        Args:
            value (object): Closed response data, with exports already signed and encrypted.

        Returns:
            Response: Native binary result without intermediary cache permission.
        """
        return Response(codec.encode(value, codec.Limits(bytes=service.budget.bytes)), status=HTTPStatus.OK, mimetype="application/cbor")

    @blueprint.post("/v1/migrate")
    def cutover() -> Response:
        """
        Execute or resume a separately authorized migration to one configured backend.

        Returns:
            Response: Durable next-epoch receipt after verified exact-history cutover.
        """
        access, arguments = decode(service, authenticate)
        args = mapping(arguments, {"operation", "destination"})
        destination = targets.get(text(args["destination"]))
        if destination is None:
            raise NativeError("denied")
        return respond(as_data(migrate(service, destination, access, text(args["operation"]))))

    @blueprint.post("/v1/migration-abort")
    def cancel() -> Response:
        """
        Explicitly cancel only a migration that has no prepared cutover effect.

        Returns:
            Response: Source-unfrozen acknowledgment; retained partial copies are not removed.
        """
        access, arguments = decode(service, authenticate)
        args = mapping(arguments, {"operation"})
        abort(service, access, text(args["operation"]))
        return respond({"outcome": "source-unfrozen"})

    @blueprint.post("/v1/rotate")
    def rotation() -> Response:
        """
        Rotate current representations using configured custody, never request-supplied key credentials.

        Returns:
            Response: Durable representation-change receipt with historical keys still required for history.
        """
        access, arguments = decode(service, authenticate)
        args = mapping(arguments, {"operation", "mode"})
        modes: dict[str, Literal["rewrap", "reseal", "resign"]] = {"rewrap": "rewrap", "reseal": "reseal", "resign": "resign"}
        mode = modes.get(text(args["mode"]))
        if mode is None:
            raise NativeError("invalid")
        return respond(as_data(rotate(service, access, text(args["operation"]), mode)))

    @blueprint.post("/v1/export")
    def export() -> Response:
        """
        Release a complete signed encrypted recovery package under current operational custody.

        Returns:
            Response: Explicit context and encrypted bytes, never a plaintext compatibility export.
        """
        access, arguments = decode(service, authenticate)
        mapping(arguments, set())
        context, sealed = archive(service, access)
        return respond({"context": context.data(), "sealed": sealed})

    @blueprint.post("/v1/restore")
    def recovery() -> Response:
        """
        Verify and copy a recovery package into an explicit inactive destination without selecting it as authority.

        Returns:
            Response: Restored opaque frontier; routing and current epoch remain unchanged.
        """
        access, arguments = decode(service, authenticate)
        args = mapping(arguments, {"destination", "context", "sealed"})
        destination = targets.get(text(args["destination"]))
        if destination is None:
            raise NativeError("denied")
        destination.protection()
        head = restore(service, access, parse(args["context"], Context), binary(args["sealed"]), destination.store)
        destination.protection()
        return respond({"generation": head.generation, "root": head.root, "digest": head.digest.hex()})

    return blueprint
