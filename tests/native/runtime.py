"""
Exercise real native transactions and authority fencing with independent PostgreSQL roles and synthetic keys.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from attrs import frozen
from witful.lessons import new_lesson
from witful.native.authority import Access, Authority
from witful.native.domains import Entry
from witful.native.git import Git, git
from witful.native.postgres import Postgres
from witful.native.service import Service
from witful.native.storage import Scope

if TYPE_CHECKING:
    from pathlib import Path

    from witful.native.storage import Store

    from tests.native.conftest import Fixture
    from tests.native.database import Databases


@frozen
class Runtime:
    """
    Pair an actual service with an independently provisioned test-only grant.

    Attributes:
        service (Service): Real service and selected ciphertext backend.
        access (Access): Synthetic current whole-identity grant.
    """

    service: Service
    access: Access


@pytest.fixture(params=("postgres", "git"))
def runtime(request: pytest.FixtureRequest, databases: Databases, fixture: Fixture, tmp_path: Path) -> Runtime:
    """
    Run the same service contract against independent data backends and shared durable authority.

    Args:
        request (pytest.FixtureRequest): Backend parameter.
        databases (Databases): Disposable separate PostgreSQL services.
        fixture (Fixture): Real envelope cryptography with synthetic keys.
        tmp_path (Path): Test-only ciphertext repository location.

    Returns:
        Runtime: Ready authenticated test scope.
    """
    scope = Scope(str(uuid4()), str(uuid4()))
    backend = str(uuid4())
    access = Access(scope, "a" * 64, str(uuid4()), str(uuid4()), 1, str(uuid4()))
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute(
            "INSERT INTO witful_native_registry (tenant, identity_id, backend, epoch, policy_revision) VALUES (%s,%s,%s,1,%s)",
            (scope.tenant, scope.identity, backend, access.policy),
        )
        admin.execute(
            "INSERT INTO witful_native_grants "
            "(tenant, identity_id, policy_revision, id, subject, task_id, actions, records, starts_at, expires) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0,4102444800)",
            (
                scope.tenant,
                scope.identity,
                access.policy,
                access.grant,
                access.subject,
                access.task,
                ["read", "write", "traverse", "recover", "export"],
                ["*"],
            ),
        )
    store: Store
    if request.param == "git":
        git(tmp_path, ("init", "--bare", "."))
        store = Git(tmp_path, "Synthetic Contract", "contract@example.invalid")
    else:
        store = Postgres(databases.data)
    return Runtime(Service(store, Authority(databases.authority, backend), lambda _: fixture.service, lambda: None), access)


def lesson(label: str = "synthetic-native-canary-3897") -> Entry:
    """
    Produce a valid legacy-hash lesson rather than bypassing domain validation for integration tests.

    Args:
        label (str): Synthetic private-content canary.

    Returns:
        Entry: Individually typed lesson.
    """
    return Entry("lesson", asdict(new_lesson("Synthetic", label, "contract test", "2026-10-15T00:00:00+00:00")))
