"""
Share the authenticated, closed binary request boundary across native domain blueprints.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from flask import request

from witful.exceptions import NativeError
from witful.native import codec
from witful.native.authority import Access
from witful.native.storage import Scope
from witful.native.wire import integer, mapping, text

if TYPE_CHECKING:
    from collections.abc import Callable

    from witful.native.service import Service


def decode(service: Service, authenticate: Callable[[], str]) -> tuple[Access, object]:
    """
    Authenticate the actual transport before decoding a bounded, closed native request.

    Args:
        service (Service): Current protected runtime.
        authenticate (Callable[[], str]): Verified TLS peer identity boundary.

    Returns:
        tuple[Access, object]: Typed authentication bindings and operation-owned arguments.
    """
    access, arguments = decode_request(authenticate, service.protection, service.budget.bytes)
    if (access.scope.tenant, access.scope.identity) in service.graph_scopes:
        raise NativeError("denied")
    return access, arguments


def decode_request(authenticate: Callable[[], str], protection: Callable[[], None], byte_limit: int) -> tuple[Access, object]:
    """
    Reuse the same authenticated wire boundary for independently deployed native and projection roles.

    Args:
        authenticate (Callable[[], str]): Verified TLS peer identity boundary.
        protection (Callable[[], None]): Role-specific protected-working-storage check.
        byte_limit (int): Explicit complete request byte budget.

    Returns:
        tuple[Access, object]: Closed request bindings derived from the actual authenticated peer.
    """
    subject = authenticate()
    protection()
    if request.mimetype != "application/cbor":
        raise NativeError("invalid")
    body = mapping(codec.decode(request.get_data(), codec.Limits(bytes=byte_limit)), {"access", "arguments"})
    binding = mapping(body["access"], {"tenant", "identity", "grant", "task", "epoch", "policy"})
    access = Access(
        Scope(text(binding["tenant"]), text(binding["identity"])),
        subject,
        text(binding["grant"]),
        text(binding["task"]),
        integer(binding["epoch"]),
        text(binding["policy"]),
    )
    return access, body["arguments"]
