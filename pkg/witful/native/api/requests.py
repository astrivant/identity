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
    subject = authenticate()
    service.protection()
    if request.mimetype != "application/cbor":
        raise NativeError("invalid")
    body = mapping(codec.decode(request.get_data(), codec.Limits(bytes=service.budget.bytes)), {"access", "arguments"})
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
