"""
Exercise transaction ownership, atomic rollback and competing native enrollments against PostgreSQL.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from attrs import evolve
from witful.native.administration import Enrollment, enrollment
from witful.native.authority import Access
from witful.native.storage import Scope

from tests.native.database import isolated

if TYPE_CHECKING:
    from psycopg.errors import Diagnostic

    from tests.native.database import Databases


def candidate() -> Enrollment:
    """
    Construct an independent synthetic enrollment without creating runtime data.

    Returns:
        Enrollment: Valid unique registration and grant bindings.
    """
    access = Access(Scope(str(uuid4()), str(uuid4())), "a" * 64, str(uuid4()), str(uuid4()), 1, str(uuid4()))
    return Enrollment(access, str(uuid4()), ("read",), ("*",), 0, 4102444800)


def test_database_setup_has_no_nested_transaction_warning(databases: Databases, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Observe real server diagnostics while the shared fixture applies both complete provisioning plans.

    Args:
        databases (Databases): Disposable test administrator endpoint.
        monkeypatch (pytest.MonkeyPatch): Attach a notice observer without changing transaction settings.

    Returns:
        None: Schema setup owns exactly one transaction and emits no active-transaction warning.
    """
    states: list[str | None] = []
    original = psycopg.connect

    def notice(diagnostic: Diagnostic) -> None:
        """
        Copy diagnostic fields while the driver still owns their lifetime.

        Args:
            diagnostic (Diagnostic): Ephemeral server notice.

        Returns:
            None: The SQLSTATE is retained without SQL text or connection details.
        """
        states.append(diagnostic.sqlstate)

    def observed(conninfo: str, *, autocommit: bool = False) -> psycopg.Connection[tuple[object, ...]]:
        """
        Preserve the caller's transaction mode while observing PostgreSQL notices.

        Args:
            conninfo (str): Test-only connection string.
            autocommit (bool): Original caller-selected transaction ownership.

        Returns:
            psycopg.Connection[tuple[object, ...]]: Real instrumented connection.
        """
        connection: psycopg.Connection[tuple[object, ...]] = original(conninfo, autocommit=autocommit)
        connection.add_notice_handler(notice)
        return connection

    monkeypatch.setattr(psycopg, "connect", observed)
    with isolated(databases.data_admin):
        pass
    assert "25001" not in states, "Provisioning issued BEGIN inside an implicit transaction"


def test_enrollment_rolls_back_both_inserts_on_failure(databases: Databases) -> None:
    """
    Fail after both enrollment inserts and prove the entire plan rolls back before retry.

    Args:
        databases (Databases): Disposable independent authority database.

    Returns:
        None: A failed plan leaves neither registry nor grant rows and a corrected retry succeeds.
    """
    value = candidate()
    plan = enrollment(value)
    # Inject a server error immediately before the plan's commit, preserving both real inserts.
    interrupted = plan.removesuffix("COMMIT;\n") + "SELECT 1 / 0;\nCOMMIT;\n"
    with psycopg.connect(databases.authority_admin, autocommit=True) as connection:
        with pytest.raises(psycopg.errors.DivisionByZero):
            connection.execute(interrupted)
        connection.rollback()
        for table in ("witful_native_registry", "witful_native_grants"):
            row = connection.execute(
                psycopg.sql.SQL("SELECT count(*) FROM {} WHERE tenant = %s AND identity_id = %s").format(psycopg.sql.Identifier(table)),
                (value.access.scope.tenant, value.access.scope.identity),
            ).fetchone()
            assert row == (0,)
        connection.execute(plan)
        assert connection.info.transaction_status == psycopg.pq.TransactionStatus.IDLE


@pytest.mark.parametrize("changed_grant", [False, True])
def test_competing_enrollments_preserve_one_registration(databases: Databases, changed_grant: bool) -> None:
    """
    Race two real database sessions and retain the winner's single grant without an application lock.

    Args:
        databases (Databases): Disposable independent authority database.
        changed_grant (bool): Compete with an exact replay or a different requested grant.

    Returns:
        None: PostgreSQL accepts one plan, rejects the duplicate and leaves no partial grant expansion.
    """
    value = candidate()
    competitor = evolve(value, access=evolve(value.access, grant=str(uuid4())), actions=("read", "write")) if changed_grant else value
    gate = Barrier(2)

    def submit(request: Enrollment) -> tuple[str, str]:
        """
        Submit a complete plan from an independently owned connection after both writers are ready.

        Args:
            request (Enrollment): One competing synthetic candidate.

        Returns:
            tuple[str, str]: Accepted grant or the exact rejected constraint and candidate grant.
        """
        with psycopg.connect(databases.authority_admin, autocommit=True, options="-c statement_timeout=5000") as connection:
            gate.wait(timeout=5)
            try:
                connection.execute(enrollment(request))
            except psycopg.errors.UniqueViolation as error:
                constraint = error.diag.constraint_name
                connection.rollback()
                assert constraint is not None
                return constraint, request.access.grant
            return "accepted", request.access.grant

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, (value, competitor)))
    assert sorted(status for status, _ in results) == ["accepted", "witful_native_registry_pkey"]
    winner = next(grant for status, grant in results if status == "accepted")
    expected = value if winner == value.access.grant else competitor
    with psycopg.connect(databases.authority_admin, autocommit=True) as connection:
        registration = connection.execute(
            "SELECT backend, epoch, policy_revision, generation FROM witful_native_registry WHERE tenant = %s AND identity_id = %s",
            (value.access.scope.tenant, value.access.scope.identity),
        ).fetchall()
        grants = connection.execute(
            "SELECT id, actions FROM witful_native_grants WHERE tenant = %s AND identity_id = %s",
            (value.access.scope.tenant, value.access.scope.identity),
        ).fetchall()
    assert len(registration) == 1
    assert tuple(str(item) for item in registration[0]) == (value.backend, "1", value.access.policy, "0")
    assert len(grants) == 1 and str(grants[0][0]) == winner and grants[0][1] == list(expected.actions)
