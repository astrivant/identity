"""
Release recipient-only encrypted snapshots through identity-bound operator-configured public aliases.
"""

from __future__ import annotations

import base64
from http import HTTPStatus
from typing import TYPE_CHECKING

from flask import Blueprint, Response

from witful.exceptions import NativeError
from witful.native import codec
from witful.native.api.requests import decode
from witful.native.sharing import Recipient, create
from witful.native.wire import mapping, text

if TYPE_CHECKING:
    from collections.abc import Callable

    from witful.native.config import ExportRecipient
    from witful.native.service import Service


def routes(service: Service, authenticate: Callable[[], str], recipients: tuple[ExportRecipient, ...]) -> Blueprint:
    """
    Compose sharing with the existing authenticated application, current export grants and release checks.

    Args:
        service (Service): Controller-owned source and custody.
        authenticate (Callable[[], str]): Verified mutual TLS peer boundary.
        recipients (tuple[ExportRecipient, ...]): Reviewed scoped public recipients; no private recipient key is installed here.

    Returns:
        Blueprint: Explicit sharing endpoint with no automatic publication or received-instruction activation.
    """
    blueprint = Blueprint("native_sharing", __name__)

    @blueprint.post("/v1/share")
    def share() -> Response:
        """
        Select only an operator-reviewed recipient for the admitted tenant and identity, or current owner custody.

        Returns:
            Response: Sender-signed encrypted snapshot including the exact historical data keys inside recipient encryption.
        """
        access, arguments = decode(service, authenticate)
        args = mapping(arguments, {"recipient"})
        recipient = None
        if args["recipient"] is not None:
            name = text(args["recipient"])
            configured = next((value for value in recipients if value.name == name), None)
            if configured is None or (configured.tenant, configured.identity) != (access.scope.tenant, access.scope.identity):
                raise NativeError("denied")
            recipient = Recipient(configured.generation, base64.b64decode(configured.public, validate=True), configured.fingerprint)
        context, sealed = create(service, access, recipient)
        return Response(
            codec.encode({"context": context.data(), "sealed": sealed}, codec.Limits(bytes=service.budget.bytes)),
            status=HTTPStatus.OK,
            mimetype="application/cbor",
        )

    return blueprint
