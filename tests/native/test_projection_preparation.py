"""
Exercise durable exact-candidate preparation against both real backends without any remote side effect.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from attrs import evolve
from witful.exceptions import NativeError
from witful.native.backup import Archive, verify
from witful.native.projection.models import PREPARED
from witful.native.projection.preparation import load, prepare

from tests.native.projection import configured
from tests.native.runtime import lesson

if TYPE_CHECKING:
    from tests.native.database import Databases
    from tests.native.runtime import Runtime


def test_prepared_candidate_is_durable_and_exact_on_retry(runtime: Runtime, databases: Databases) -> None:
    """
    Reuse original ciphertext, Git metadata and outbox pointers after a process reconstruction and policy scheduling change.

    Args:
        runtime (Runtime): Real Git or PostgreSQL backend with independent authority.
        databases (Databases): Explicit synthetic grant administrator.

    Returns:
        None: Preparation is complete before transport and current revocation prevents candidate release.
    """
    service = configured(runtime, databases)
    receipt = service.append(runtime.access, str(uuid4()), "main", None, (lesson(),))
    target = service.projection.targets[0].id
    pointer, prepared = prepare(service, runtime.access, target, "Synthetic Export", "export@example.invalid")
    assert pointer.kind == PREPARED and prepared.intent.generation == receipt.generation and prepared.intent.required
    bundle, permit, envelope = load(service, runtime.access, prepared)
    assert permit.oid == prepared.oid and permit.expected is None
    assert b"synthetic-native-canary" not in bundle.blob and b"Synthetic Export" not in envelope
    head = service.store.head(runtime.access.scope)
    restarted = evolve(service, projection=evolve(service.projection, mode="disabled"))
    assert prepare(restarted, runtime.access, target, "Different Retry", "retry@example.invalid") == (pointer, prepared)
    assert load(restarted, runtime.access, prepared) == (bundle, permit, envelope)
    assert service.store.head(runtime.access.scope) == head
    verify(service, runtime.access, Archive(runtime.access.scope, service.store.history(runtime.access.scope)))
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute("DELETE FROM witful_native_grants WHERE id=%s", (runtime.access.grant,))
    with pytest.raises(NativeError, match="denied"):
        prepare(service, runtime.access, target, "Synthetic Export", "export@example.invalid")
    assert service.store.head(runtime.access.scope) == head


def test_preparation_refuses_oversized_retry_bytes_without_advancing(runtime: Runtime, databases: Databases) -> None:
    """
    Leave accepted work pending when encrypted candidate bytes exceed the explicitly selected queue budget.

    Args:
        runtime (Runtime): Real native backend.
        databases (Databases): Explicit synthetic grant administrator.

    Returns:
        None: Refusal neither drops accepted intent nor commits a partial candidate.
    """
    service = configured(runtime, databases)
    service.append(runtime.access, str(uuid4()), "main", None, (lesson(),))
    head = service.store.head(runtime.access.scope)
    limited = evolve(service, projection=evolve(service.projection, max_bytes=1))
    with pytest.raises(NativeError, match="unavailable"):
        prepare(limited, runtime.access, service.projection.targets[0].id, "Synthetic Export", "export@example.invalid")
    assert service.store.head(runtime.access.scope) == head
