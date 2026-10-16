"""
Exercise migration, encrypted export/restore and rotation through one application's public binary boundary.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from uuid import uuid4

from attrs import evolve
from witful.native import codec
from witful.native.api.admission import Admission
from witful.native.api.builder import Builder
from witful.native.wire import mapping

from tests.native.requests import body
from tests.native.runtime import lesson

if TYPE_CHECKING:
    from witful.native.service import Service

    from tests.native.runtime import Runtime


def test_export_restore_and_cutover_routes(runtime: Runtime, destination: Service) -> None:
    """
    Restore a signed encrypted package without routing change, then migrate that exact prefix under current authorization.

    Args:
        runtime (Runtime): Real native source.
        destination (Service): Explicit inactive destination of the other backend kind.

    Returns:
        None: Authenticated API operations preserve history, expose the next epoch and deny unknown destinations.
    """
    source, access = runtime.service, runtime.access
    source.append(access, str(uuid4()), "main", None, (lesson(),))
    client = Builder(source, Admission(1), lambda: True, lambda: access.subject, (destination,)).build().test_client()
    exported = client.post("/v1/export", data=body(runtime, {}), content_type="application/cbor")
    assert exported.status_code == HTTPStatus.OK
    package = mapping(codec.decode(exported.data), {"context", "sealed"})
    assert b"synthetic-native-canary" not in exported.data
    restored = client.post(
        "/v1/restore", data=body(runtime, {**package, "destination": destination.authority.backend}), content_type="application/cbor"
    )
    assert restored.status_code == HTTPStatus.OK
    assert source.history(access, "main")
    arguments = {"operation": str(uuid4()), "destination": str(uuid4())}
    refused = client.post("/v1/migrate", data=body(runtime, arguments), content_type="application/cbor")
    assert refused.status_code == HTTPStatus.FORBIDDEN
    arguments["destination"] = destination.authority.backend
    migrated = client.post("/v1/migrate", data=body(runtime, arguments), content_type="application/cbor")
    assert migrated.status_code == HTTPStatus.OK
    receipt = codec.decode(migrated.data)
    assert isinstance(receipt, dict) and receipt["epoch"] == 2
    assert len(destination.history(evolve(access, epoch=2), "main")) == 1


def test_rotation_route_has_closed_modes(runtime: Runtime) -> None:
    """
    Reject unsupported rotation semantics and use only the server's configured custody for valid requests.

    Args:
        runtime (Runtime): Actual native source and synthetic key boundary.

    Returns:
        None: Invalid input makes no mutation while explicit resealing retains logical history.
    """
    source, access = runtime.service, runtime.access
    source.append(access, str(uuid4()), "main", None, (lesson(),))
    original = source.store.head(access.scope)
    client = Builder(source, Admission(1), lambda: True, lambda: access.subject).build().test_client()
    arguments = {"operation": str(uuid4()), "mode": "replace-old-history"}
    invalid = client.post("/v1/rotate", data=body(runtime, arguments), content_type="application/cbor")
    assert invalid.status_code == HTTPStatus.BAD_REQUEST
    assert source.store.head(access.scope) == original
    arguments["mode"] = "reseal"
    valid = client.post("/v1/rotate", data=body(runtime, arguments), content_type="application/cbor")
    assert valid.status_code == HTTPStatus.OK
    assert len(source.history(access, "main")) == 1
