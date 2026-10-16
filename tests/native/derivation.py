"""
Provision synthetic independent recipient scopes explicitly, without making the implementation an authority administrator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
from attrs import evolve
from witful.native.derivation import Child
from witful.native.reconciliation import Selection
from witful.native.storage import Scope

from tests.native.runtime import lesson

if TYPE_CHECKING:
    from tests.native.database import Databases
    from tests.native.runtime import Runtime


def children(runtime: Runtime, databases: Databases) -> tuple[str, tuple[Child, ...]]:
    """
    Build a reviewed parent and two separately granted empty children, with one deliberately omitted source record.

    Args:
        runtime (Runtime): Current synthetic parent.
        databases (Databases): Test-only independently administered authority.

    Returns:
        tuple[str, tuple[Child, ...]]: Pinned parent frontier and reviewed selections with explicit child grants.
    """
    entries = (lesson("selected-one"), lesson("selected-two"), lesson("omitted-private-canary"))
    runtime.service.append(runtime.access, str(uuid4()), "main", None, entries, b"whole-source-private-canary")
    history = runtime.service.history(runtime.access, "main")
    result: list[Child] = []
    for revision, entry in history[:2]:
        access = evolve(runtime.access, scope=Scope(runtime.access.scope.tenant, str(uuid4())), grant=str(uuid4()), task=str(uuid4()))
        with psycopg.connect(databases.authority_admin) as admin:
            admin.execute(
                "INSERT INTO witful_native_registry (tenant, identity_id, backend, epoch, policy_revision) VALUES (%s,%s,%s,%s,%s)",
                (access.scope.tenant, access.scope.identity, runtime.service.authority.backend, access.epoch, access.policy),
            )
            admin.execute(
                "INSERT INTO witful_native_grants "
                "(tenant, identity_id, policy_revision, id, subject, task_id, actions, records, starts_at, expires) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0,4102444800)",
                (
                    access.scope.tenant,
                    access.scope.identity,
                    access.policy,
                    access.grant,
                    access.subject,
                    access.task,
                    ["derive", "import", "write", "read", "traverse", "export", "recover"],
                    ["*"],
                ),
            )
        result.append(Child(runtime.service, access, "main", (Selection((revision.id,), entry),)))
    head = runtime.service.store.head(runtime.access.scope)
    assert head.root is not None
    return head.root, tuple(result)
