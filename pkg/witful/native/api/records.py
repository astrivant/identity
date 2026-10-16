"""
Keep native record routes thin over the authenticated, fenced domain service.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from flask import Blueprint, Response

from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native import codec, domains
from witful.native.api.requests import decode
from witful.native.cache import conditional_read
from witful.native.reconciliation import Selection, merge
from witful.native.wire import mapping, sequence, text

if TYPE_CHECKING:
    from collections.abc import Callable

    from witful.native.service import Service


def routes(service: Service, authenticate: Callable[[], str]) -> Blueprint:
    """
    Assemble record operations with one trusted transport identity boundary.

    Args:
        service (Service): Injected native domain runtime.
        authenticate (Callable[[], str]): Actual verified TLS peer fingerprint, never forwarded HTTP input.

    Returns:
        Blueprint: Closed binary API under the application-owned central error and admission boundaries.
    """
    blueprint = Blueprint("native_records", __name__)

    @blueprint.post("/v1/<operation>")
    def execute(operation: str) -> Response:
        """
        Dispatch a closed operation after authenticating the transport and validating its complete binary request.

        Args:
            operation (str): Native API route operation.

        Returns:
            Response: Bounded CBOR result or a centrally redacted domain error.
        """
        access, arguments = decode(service, authenticate)
        result: object
        if operation == "append":
            args = mapping(arguments, {"operation", "ref", "expected", "entries"})
            entries = tuple(domains.decode(value) for value in sequence(args["entries"]))
            result = as_data(
                service.append(
                    access,
                    text(args["operation"]),
                    text(args["ref"]),
                    None if args["expected"] is None else text(args["expected"]),
                    entries,
                )
            )
        elif operation == "read-conditional":
            args = mapping(arguments, {"record", "token"})
            result = conditional_read(service, access, text(args["record"]), None if args["token"] is None else text(args["token"]))
        elif operation == "read":
            args = mapping(arguments, {"record"})
            result = domains.encode(service.read(access, text(args["record"])))
        elif operation == "history":
            args = mapping(arguments, {"ref"})
            result = [
                {"revision": as_data(revision), "entry": domains.encode(entry)}
                for revision, entry in service.history(access, text(args["ref"]))
            ]
        elif operation == "search":
            args = mapping(arguments, {"ref", "query"})
            result = list(service.search(access, text(args["ref"]), text(args["query"])))
        elif operation == "branch":
            args = mapping(arguments, {"operation", "name", "record", "immutable"})
            if type(args["immutable"]) is not bool:
                raise NativeError("invalid")
            result = as_data(service.branch(access, text(args["operation"]), text(args["name"]), text(args["record"]), args["immutable"]))
        elif operation == "merge":
            args = mapping(arguments, {"operation", "target", "candidate", "expected", "reviewed", "selections", "reason"})
            selections: list[Selection] = []
            for item in sequence(args["selections"]):
                selected = mapping(item, {"sources", "entry"})
                selections.append(
                    Selection(tuple(text(source) for source in sequence(selected["sources"])), domains.decode(selected["entry"]))
                )
            result = as_data(
                merge(
                    service,
                    access,
                    text(args["operation"]),
                    text(args["target"]),
                    text(args["candidate"]),
                    text(args["expected"]),
                    text(args["reviewed"]),
                    tuple(selections),
                    text(args["reason"]),
                )
            )
        elif operation == "recover":
            mapping(arguments, set())
            head = service.authority.recover(access, service.store, int(service.clock()))
            result = {"generation": head.generation, "root": head.root, "digest": head.digest.hex()}
        else:
            raise NativeError("unsupported")
        return Response(codec.encode(result, codec.Limits(bytes=service.budget.bytes)), status=HTTPStatus.OK, mimetype="application/cbor")

    return blueprint
