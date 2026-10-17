"""
Compose intent discovery into the existing mTLS, admission, error and metrics application.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from flask import Blueprint, Response

from witful.codegraph.service import RepositoryGraph
from witful.context.models import Limits
from witful.exceptions import NativeError
from witful.intent.models import Query, Review, State
from witful.intent.service import IntentGraph
from witful.knowledge.contracts import as_data
from witful.native import codec
from witful.native.api.requests import decode_request
from witful.native.models import parse
from witful.native.wire import integer, mapping, text
from witful.repertoire.models import Inventory

if TYPE_CHECKING:
    from collections.abc import Callable

    from witful.codegraph.models import Enrollment
    from witful.native.service import Service


def routes(service: Service, authenticate: Callable[[], str], enrollments: tuple[Enrollment, ...]) -> Blueprint:
    """
    Require an existing graph enrollment and independent intent grants before reading private state.

    Args:
        service (Service): Existing protected native runtime.
        authenticate (Callable[[], str]): Actual verified mTLS peer identity.
        enrollments (tuple[Enrollment, ...]): Signed-config graph scopes.

    Returns:
        Blueprint: Domain routes with no separate listener or authorization implementation.
    """
    blueprint = Blueprint("intent", __name__)

    @blueprint.post("/v1/intent-<operation>")
    def execute(operation: str) -> Response:
        """
        Dispatch closed typed operations without arbitrary code or caller-owned reviewer identity.

        Args:
            operation (str): Explicit facade leaf.

        Returns:
            Response: Bounded protected evidence or an opaque native receipt.
        """
        access, arguments = decode_request(authenticate, service.protection, service.budget.bytes)
        enrollment = next(
            (item for item in enrollments if (item.tenant, item.extension) == (access.scope.tenant, access.scope.identity)), None
        )
        if enrollment is None:
            raise NativeError("denied")
        intent = IntentGraph(RepositoryGraph(service, enrollment))
        result: object
        if operation == "publish":
            args = mapping(arguments, {"operation", "expected", "state"})
            result = intent.publish(
                access, text(args["operation"]), None if args["expected"] is None else text(args["expected"]), parse(args["state"], State)
            )
        elif operation == "review":
            args = mapping(arguments, {"operation", "expected", "decision"})
            result = intent.review(access, text(args["operation"]), text(args["expected"]), parse(args["decision"], Review))
        elif operation == "draft":
            args = mapping(arguments, {"inventory", "limits"})
            result = intent.draft(access, parse(args["inventory"], Inventory), parse(args["limits"], Limits))
        elif operation == "query":
            args = mapping(arguments, {"query", "limits"})
            result = intent.query(access, parse(args["query"], Query), parse(args["limits"], Limits))
        elif operation == "source":
            args = mapping(arguments, {"anchor", "digest", "start", "end", "limits"})
            result = intent.source(
                access,
                text(args["anchor"]),
                text(args["digest"]),
                integer(args["start"]),
                integer(args["end"]),
                parse(args["limits"], Limits),
            )
        else:
            raise NativeError("unsupported")
        return Response(codec.encode(as_data(result), codec.Limits(bytes=service.budget.bytes)), mimetype="application/cbor")

    return blueprint
