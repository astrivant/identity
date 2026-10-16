"""
Exercise persisted retry progress and required-completion gates across a lost gateway acknowledgment and actual remote publication.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
from attrs import evolve
from witful.exceptions import NativeError
from witful.native.backup import Archive, verify
from witful.native.git import git
from witful.native.projection.gateway import Destination, Gateway
from witful.native.projection.status import completion, status
from witful.native.projection.transport import GitRemote
from witful.native.projection.worker import deliver
from witful.native.wire import binary, integer

from tests.native.projection import PermitKeys, configured
from tests.native.runtime import lesson

if TYPE_CHECKING:
    from pathlib import Path

    from witful.native.authority import Access
    from witful.native.projection.models import Target

    from tests.native.database import Databases
    from tests.native.runtime import Runtime


def test_required_delivery_survives_lost_reply_and_process_reconstruction(runtime: Runtime, databases: Databases, tmp_path: Path) -> None:
    """
    Keep required work pending after an actual successful remote update whose reply was lost, then verify exact bytes on retry.

    Args:
        runtime (Runtime): Real Git or PostgreSQL native source.
        databases (Databases): Synthetic independent policy administrator.
        tmp_path (Path): Disposable remote and gateway directories.

    Returns:
        None: Exact retries clear the gate only after verification and subsequent publication extends the acknowledged remote parent.
    """
    service = configured(runtime, databases)
    operation = str(uuid4())
    receipt = service.append(runtime.access, operation, "main", None, (lesson(),))
    assert receipt.remote_required and not completion(service, runtime.access, operation)["complete"]
    target = service.projection.targets[0]
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
        target.id,
        runtime.access.scope,
        GitRemote(working, remote.as_uri(), "refs/heads/projection", {}),
        "Synthetic Export",
        "fixture@example.invalid",
    )
    original = service.keys(runtime.access)
    keys = evolve(
        original, wrapping=service.projection.permit_wrapping, keys=PermitKeys(original.keys, service.projection.permit_wrapping, [])
    )
    gateway = Gateway(service.authority, (destination,), lambda _: keys, lambda: None, service.budget)
    requests: list[dict[str, object]] = []

    def send(target: Target, access: Access, arguments: dict[str, object], byte_limit: int) -> object:
        """
        Exercise real gateway publication while losing exactly the first successful response.

        Args:
            target (Target): Exact retained destination.
            access (Access): Actual worker bindings.
            arguments (dict[str, object]): Complete prepared candidate and permit.
            byte_limit (int): Original complete request budget.

        Returns:
            object: Actual verified gateway response except the first deliberately lost acknowledgment.
        """
        assert access == runtime.access and byte_limit == service.budget.bytes
        requests.append(arguments)
        result = gateway.deliver(delegate, target.id, str(arguments["operation"]), binary(arguments["permit"]), binary(arguments["bundle"]))
        if len(requests) == 1:
            raise NativeError("unknown")
        return result

    assert deliver(service, runtime.access, target.id, destination.author, destination.email, send)["state"] == "unknown"
    assert not completion(service, runtime.access, operation)["complete"]
    pending = status(service, runtime.access)
    assert pending["queue_size"] == 1 and integer(pending["queue_bytes"]) > 0
    now = service.clock()
    restarted = evolve(service, clock=lambda: now + 2, projection=evolve(service.projection, mode="disabled"))
    assert not completion(restarted, runtime.access, operation)["complete"]
    result = deliver(restarted, runtime.access, target.id, destination.author, destination.email, send)
    assert result["state"] == "remote_verified" and requests[0] == requests[1]
    assert completion(restarted, runtime.access, operation) == {
        "operation": operation,
        "durability": "durable",
        "remote_required": True,
        "complete": True,
        "pending": 0,
        "verified": 1,
    }
    assert status(restarted, runtime.access)["queue_size"] == 0
    previous = service.history(runtime.access, "main")[-1][0].id
    second = str(uuid4())
    service.append(runtime.access, second, "main", previous, (lesson("second"),))
    next_result = deliver(service, runtime.access, target.id, destination.author, destination.email, send)
    assert next_result["state"] == "remote_verified"
    assert git(remote, ("rev-list", "--parents", "-1", str(next_result["oid"]))).strip().decode().split() == [
        next_result["oid"],
        result["oid"],
    ]
    verify(service, runtime.access, Archive(runtime.access.scope, service.store.history(runtime.access.scope)))


def test_missing_pending_entry_does_not_satisfy_required_destination_set(runtime: Runtime, databases: Databases) -> None:
    """
    Detect a missing outbox entry by comparing completion against the originally accepted destination set.

    Args:
        runtime (Runtime): Real native backend.
        databases (Databases): Explicit synthetic grant administrator.

    Returns:
        None: One verified destination cannot close a two-destination requirement even when the pending index is accidentally emptied.
    """
    service = configured(runtime, databases)
    first_target = service.projection.targets[0]
    second_target = evolve(first_target, id=str(uuid4()))
    service = evolve(service, projection=evolve(service.projection, targets=(first_target, second_target), max_entries=2))
    operation = str(uuid4())
    service.append(runtime.access, operation, "main", None, (lesson(),))

    def verified(target: Target, access: Access, arguments: dict[str, object], byte_limit: int) -> object:
        """
        Supply one trusted gateway result solely to exercise native completion bookkeeping; remote transport is tested separately.

        Args:
            target (Target): Selected destination.
            access (Access): Current worker bindings.
            arguments (dict[str, object]): Complete prepared candidate.
            byte_limit (int): Explicit wire budget.

        Returns:
            object: Exact synthetic verified response for the first accepted destination only.
        """
        from witful.native.projection.bundle import Bundle

        bundle = Bundle.decode(binary(arguments["bundle"]), service.keys(access).limits)
        assert target == first_target and byte_limit == service.budget.bytes
        return {"state": "remote_verified", "operation": operation, "target": target.id, "generation": 1, "oid": bundle.objects()[-1][1]}

    deliver(service, runtime.access, first_target.id, "Synthetic Export", "fixture@example.invalid", verified)
    registration, frontier = service.snapshot(runtime.access, "write", "*")
    assert len(frontier.outbox) == 1
    service.commit(
        runtime.access,
        str(uuid4()),
        "synthetic-missing-index-fault",
        registration,
        evolve(frontier, outbox=()),
        (),
        service.monotonic(),
        project=False,
    )
    result = completion(service, runtime.access, operation)
    assert result["pending"] == 0 and result["verified"] == 1 and result["complete"] is False
