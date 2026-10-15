"""
Verify atomic encrypted projection intent, current export permission and backlog refusal without contacting a remote.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from witful.exceptions import NativeError
from witful.native.backup import Archive, verify
from witful.native.models import parse
from witful.native.projection.models import INTENT, Intent

from tests.native.projection import configured
from tests.native.runtime import lesson

if TYPE_CHECKING:
    from tests.native.database import Databases
    from tests.native.runtime import Runtime


def test_outbox_commits_with_accepted_records_and_receipt(runtime: Runtime, databases: Databases) -> None:
    """
    Persist queue intent in the same backend transaction and refuse another write when the verified backlog budget is exhausted.

    Args:
        runtime (Runtime): Actual Git or PostgreSQL source.
        databases (Databases): Explicit synthetic projection authorization.

    Returns:
        None: Accepted state includes encrypted pending work, complete backup verifies and a refused write changes no frontier.
    """
    service = configured(runtime, databases)
    operation = str(uuid4())
    receipt = service.append(runtime.access, operation, "main", None, (lesson(),))
    _, frontier = service.snapshot(runtime.access, "read", "*")
    assert len(frontier.outbox) == 1 and frontier.outbox[0].kind == INTENT
    intent = parse(service.open(runtime.access, frontier.outbox[0]), Intent)
    assert intent.operation == operation and intent.required and intent.generation == receipt.generation
    batch = service.store.history(runtime.access.scope)[0]
    assert len(batch.outbox) == 1 and batch.outbox[0].id == frontier.outbox[0].object
    assert b"gateway.invalid" not in batch.outbox[0].payload
    verify(service, runtime.access, Archive(runtime.access.scope, (batch,)))
    expected = service.history(runtime.access, "main")[-1][0].id
    with pytest.raises(NativeError, match="unavailable"):
        service.append(runtime.access, str(uuid4()), "main", expected, (lesson("next"),))
    assert service.store.head(runtime.access.scope) == batch.target
    assert service.append(runtime.access, operation, "main", None, (lesson(),)) == receipt


def test_queueing_requires_explicit_export_and_projection_authority(runtime: Runtime, databases: Databases) -> None:
    """
    Refuse configured projection when ordinary write permission lacks either explicit delivery or disclosure authority.

    Args:
        runtime (Runtime): Current authorized native writer.
        databases (Databases): Synthetic independent grant administrator.

    Returns:
        None: Configuration cannot manufacture permission to export accepted records.
    """
    service = configured(runtime, databases)
    for permission in ("project", "export"):
        with psycopg.connect(databases.authority_admin) as admin:
            admin.execute(
                "UPDATE witful_native_grants SET actions=array_remove(actions, %s) WHERE id=%s", (permission, runtime.access.grant)
            )
        with pytest.raises(NativeError, match="denied"):
            service.append(runtime.access, str(uuid4()), "main", None, (lesson(),))
        assert service.store.head(runtime.access.scope).generation == 0
        with psycopg.connect(databases.authority_admin) as admin:
            admin.execute(
                "UPDATE witful_native_grants SET actions=array_append(actions, %s) WHERE id=%s", (permission, runtime.access.grant)
            )


def test_projection_refuses_domain_wrapping_key_reuse(runtime: Runtime, databases: Databases) -> None:
    """
    Refuse a permit key that would give the gateway the same custody capability as the source identity.

    Args:
        runtime (Runtime): Actual native backend and domain wrapping generation.
        databases (Databases): Explicit synthetic projection authorization.

    Returns:
        None: The misconfigured write has no durable effect even when source grants otherwise permit it.
    """
    from attrs import evolve

    service = configured(runtime, databases)
    shared = evolve(service, projection=evolve(service.projection, permit_wrapping=service.keys(runtime.access).wrapping))
    with pytest.raises(NativeError, match="denied"):
        shared.append(runtime.access, str(uuid4()), "main", None, (lesson(),))
    assert service.store.head(runtime.access.scope).generation == 0
