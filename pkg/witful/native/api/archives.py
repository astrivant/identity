"""
Expose original Git recovery only through operator-reviewed identity-bound filesystem aliases.
"""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

from flask import Blueprint, Response

from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native import codec
from witful.native.api.requests import decode
from witful.native.models import parse
from witful.native.original_git import GIT_ARCHIVE, Repository, capture, restore
from witful.native.wire import mapping, text

if TYPE_CHECKING:
    from collections.abc import Callable

    from witful.native.config import ArchivePath
    from witful.native.service import Service


def routes(service: Service, authenticate: Callable[[], str], paths: tuple[ArchivePath, ...]) -> Blueprint:
    """
    Compose archive operations without granting clients arbitrary host filesystem access.

    Args:
        service (Service): Native protected runtime.
        authenticate (Callable[[], str]): Verified TLS peer boundary.
        paths (tuple[ArchivePath, ...]): Signed operator configuration, bound to tenant/identity and capture/restore direction.

    Returns:
        Blueprint: Original-Git operations behind the consolidated application's existing admission and diagnostics boundaries.
    """
    blueprint = Blueprint("native_archives", __name__)

    @blueprint.post("/v1/original-<operation>")
    def execute(operation: str) -> Response:
        """
        Capture, list or restore an exact original Git inventory under current authorization.

        Args:
            operation (str): Closed archive action.

        Returns:
            Response: Durable receipt or bounded inventory, never unrequested original file contents.
        """
        access, arguments = decode(service, authenticate)
        result: object
        if operation == "list":
            mapping(arguments, set())
            started = service.monotonic()
            registration, frontier = service.snapshot(access, "export", "*")
            result = [
                {"record": item.record, "inventory": as_data(parse(service.open(access, item), Repository))}
                for item in frontier.archives
                if item.kind == GIT_ARCHIVE
            ]
            service.release(access, "export", "*", registration, started)
        elif operation in {"capture", "restore"}:
            fields = {"path", "operation", "unreachable", "reflogs"} if operation == "capture" else {"path", "record"}
            args = mapping(arguments, fields)
            target = next(
                (
                    path
                    for path in paths
                    if path.name == text(args["path"])
                    and path.mode == operation
                    and path.tenant == access.scope.tenant
                    and path.identity == access.scope.identity
                ),
                None,
            )
            if target is None:
                raise NativeError("denied")
            if operation == "capture":
                if type(args["unreachable"]) is not bool or type(args["reflogs"]) is not bool:
                    raise NativeError("invalid")
                result = as_data(capture(service, access, text(args["operation"]), Path(target.path), args["unreachable"], args["reflogs"]))
            else:
                result = as_data(restore(service, access, text(args["record"]), Path(target.path)))
        else:
            raise NativeError("unsupported")
        return Response(codec.encode(result, codec.Limits(bytes=service.budget.bytes)), status=HTTPStatus.OK, mimetype="application/cbor")

    return blueprint
