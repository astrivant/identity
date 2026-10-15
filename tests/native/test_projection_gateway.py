"""
Verify isolated delivery using real policy, cryptography and Git while denying the gateway every domain-decryption operation.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from attrs import evolve
from witful.exceptions import NativeError
from witful.native import codec
from witful.native.api.admission import Admission
from witful.native.git import git
from witful.native.projection.gateway import Builder, Destination, Gateway
from witful.native.projection.models import PERMIT
from witful.native.projection.preparation import load, prepare
from witful.native.projection.transport import GitRemote

from tests.native.projection import PermitKeys, configured
from tests.native.runtime import lesson

if TYPE_CHECKING:
    from pathlib import Path

    from tests.native.database import Databases
    from tests.native.runtime import Runtime


def test_gateway_policy_key_isolation_and_same_app_boundary(runtime: Runtime, databases: Databases, tmp_path: Path) -> None:
    """
    Publish through the actual Flask route and independent grant while demonstrating that the gateway cannot decrypt identity history.

    Args:
        runtime (Runtime): Real native source backend.
        databases (Databases): Synthetic policy administrator.
        tmp_path (Path): Disposable remote and gateway working directories.

    Returns:
        None: Remote bytes verify, wrong destinations and revoked writers fail, and operational endpoints share the app.
    """
    service = configured(runtime, databases)
    operation = str(uuid4())
    service.append(runtime.access, operation, "main", None, (lesson(),))
    target = service.projection.targets[0]
    _, prepared = prepare(service, runtime.access, target.id, "Synthetic Export", "fixture@example.invalid")
    bundle, permit, envelope = load(service, runtime.access, prepared)
    delegate = evolve(runtime.access, subject="b" * 64, grant=target.grant, task=target.task)
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute(
            "INSERT INTO witful_native_grants "
            "SELECT tenant, identity_id, policy_revision, %s, %s, %s, %s, records, starts_at, expires "
            "FROM witful_native_grants WHERE id=%s",
            (delegate.grant, delegate.subject, delegate.task, ["project"], runtime.access.grant),
        )
    remote = tmp_path / "remote"
    remote.mkdir(mode=0o700)
    git(remote, ("init", "--bare", "--template=", "."))
    working = tmp_path / "gateway"
    working.mkdir(mode=0o700)
    destination = Destination(
        target.id, runtime.access.scope, GitRemote(working, remote.as_uri(), "refs/heads/projection", {}), prepared.author, prepared.email
    )
    original = service.keys(runtime.access)
    restricted = PermitKeys(original.keys, [])
    keys = evolve(original, keys=restricted)
    gateway = Gateway(service.authority, (destination,), lambda _: keys, lambda: None, service.budget)
    app = Builder(gateway, Admission(2), lambda: True, lambda: delegate.subject).build().test_client()
    arguments = {"target": target.id, "operation": operation, "permit": envelope, "bundle": bundle.encode(keys.limits)}
    binding = {
        "tenant": delegate.scope.tenant,
        "identity": delegate.scope.identity,
        "grant": delegate.grant,
        "task": delegate.task,
        "epoch": delegate.epoch,
        "policy": delegate.policy,
    }
    body = codec.encode({"access": binding, "arguments": arguments}, keys.limits)
    response = app.post("/v1/project-deliver", data=body, content_type="application/cbor")
    assert response.status_code == HTTPStatus.OK
    assert codec.decode(response.data) == {
        "state": "remote_verified",
        "operation": operation,
        "target": target.id,
        "generation": permit.intent.generation,
        "oid": prepared.oid,
    }
    assert restricted.observed == [PERMIT]
    with pytest.raises(NativeError, match="denied"):
        keys.open(permit.context, bundle.blob)
    snapshot: object = app.get("/status").get_json()
    assert isinstance(snapshot, dict) and snapshot["in_flight"] == 0
    assert app.get("/metrics").status_code == HTTPStatus.OK
    assert app.get("/live").status_code == HTTPStatus.OK
    assert app.get("/ready").status_code == HTTPStatus.OK
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute("DELETE FROM witful_native_grants WHERE id=%s", (runtime.access.grant,))
    assert app.post("/v1/project-deliver", data=body, content_type="application/cbor").status_code == HTTPStatus.FORBIDDEN
    assert git(remote, ("rev-parse", "refs/heads/projection")).strip().decode() == prepared.oid
