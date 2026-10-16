"""
Expose bounded graph operations through the existing authenticated single Flask application.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from flask import Blueprint, Response

from witful.codegraph.service import RepositoryGraph
from witful.context.models import Limits
from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native import codec
from witful.native.api.requests import decode_request
from witful.native.models import parse
from witful.native.wire import integer, mapping, text

if TYPE_CHECKING:
    from collections.abc import Callable

    from witful.codegraph.models import Enrollment
    from witful.native.service import Service


def routes(service: Service, authenticate: Callable[[], str], enrollments: tuple[Enrollment, ...]) -> Blueprint:
    """
    Route only signed-config enrollments, never arbitrary request paths or self-declared owners.

    Args:
        service (Service): Existing native runtime.
        authenticate (Callable[[], str]): Verified actual mTLS peer identity.
        enrollments (tuple[Enrollment, ...]): Exact approved extension definitions.

    Returns:
        Blueprint: Optional graph endpoints under central error, admission and metrics boundaries.
    """
    blueprint = Blueprint("codegraph", __name__)

    @blueprint.post("/v1/codegraph-<operation>")
    def execute(operation: str) -> Response:
        """
        Dispatch an explicit bounded graph operation after current native admission.

        Args:
            operation (str): Selected graph operation.

        Returns:
            Response: Attributed evidence or an opaque durable build receipt.
        """
        access, arguments = decode_request(authenticate, service.protection, service.budget.bytes)
        enrollment = next(
            (item for item in enrollments if (item.tenant, item.extension) == (access.scope.tenant, access.scope.identity)), None
        )
        if enrollment is None:
            raise NativeError("denied")
        graph = RepositoryGraph(service, enrollment)
        result: object
        if operation == "build":
            args = mapping(arguments, {"operation", "revision", "expected"})
            result = graph.build(
                access, text(args["operation"]), text(args["revision"]), None if args["expected"] is None else text(args["expected"])
            )
        elif operation == "recover":
            mapping(arguments, set())
            result = graph.recover(access)
        elif operation == "rotate":
            args = mapping(arguments, {"operation", "mode"})
            mode = text(args["mode"])
            if mode == "rewrap":
                result = graph.rotate(access, text(args["operation"]), "rewrap")
            elif mode == "reseal":
                result = graph.rotate(access, text(args["operation"]), "reseal")
            elif mode == "resign":
                result = graph.rotate(access, text(args["operation"]), "resign")
            else:
                raise NativeError("invalid")
        elif operation == "query":
            args = mapping(arguments, {"revision", "symbol", "direction", "limits", "depth"})
            selected: Literal["symbol", "callers", "impact"]
            direction = text(args["direction"])
            if direction == "symbol":
                selected = "symbol"
            elif direction == "callers":
                selected = "callers"
            elif direction == "impact":
                selected = "impact"
            else:
                raise NativeError("invalid")
            result = graph.query(
                access, text(args["revision"]), text(args["symbol"]), selected, parse(args["limits"], Limits), integer(args["depth"])
            )
        else:
            raise NativeError("unsupported")
        return Response(codec.encode(as_data(result), codec.Limits(bytes=service.budget.bytes)), mimetype="application/cbor")

    return blueprint
