"""
Verify operator plans against real least-privilege databases without introducing a privileged controller API.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from attrs import evolve
from psycopg.conninfo import conninfo_to_dict
from witful import cli
from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native import administration
from witful.native.administration import Enrollment, enrollment, provision
from witful.native.postgres import sql
from witful.native.storage import Scope

if TYPE_CHECKING:
    from pathlib import Path

    from tests.native.database import Databases
    from tests.native.runtime import Runtime


def test_enrollment_is_insert_only_and_runtime_cannot_administer(runtime: Runtime, databases: Databases) -> None:
    """
    Apply an explicit synthetic new-scope plan and verify duplicates, privileged roles and runtime privilege escalation are refused.

    Args:
        runtime (Runtime): Current real storage/authority runtime.
        databases (Databases): Disposable independently administered databases.

    Returns:
        None: Plan output works; runtime roles cannot enroll, revoke grants or rewrite ciphertext history.
    """
    access = evolve(runtime.access, scope=Scope(str(uuid4()), str(uuid4())), grant=str(uuid4()), task=str(uuid4()), policy=str(uuid4()))
    value = Enrollment(access, runtime.service.authority.backend, ("read",), ("*",), 0, 4102444800)
    plan = enrollment(value)
    with psycopg.connect(
        databases.authority_admin, autocommit=True, application_name="witful-native-test:reject-duplicate-enrollment"
    ) as admin:
        admin.execute(plan)
        # This deliberate server ERROR proves duplicate enrollment cannot overwrite retained authority.
        with pytest.raises(psycopg.errors.UniqueViolation) as rejection:
            admin.execute(plan)
        assert rejection.value.diag.constraint_name == "witful_native_registry_pkey"
        admin.rollback()
    assert runtime.service.authority.check(access, "read", "*", 1).head.generation == 0
    with psycopg.connect(databases.authority, autocommit=True) as connection, pytest.raises(psycopg.errors.InsufficientPrivilege):
        connection.execute(enrollment(evolve(value, access=evolve(access, grant=str(uuid4())))))
    with psycopg.connect(databases.authority) as connection, pytest.raises(psycopg.errors.InsufficientPrivilege):
        connection.execute("UPDATE witful_native_grants SET enabled=false")
    with psycopg.connect(databases.data) as connection:
        connection.execute(sql("scope"), (runtime.access.scope.tenant, runtime.access.scope.identity))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("UPDATE witful_native_objects SET payload=''::bytea")
    owner = conninfo_to_dict(databases.data_admin).get("user", "postgres")
    assert isinstance(owner, str)
    with psycopg.connect(databases.data_admin, autocommit=True) as admin, pytest.raises(psycopg.errors.DivisionByZero):
        admin.execute(provision("data", owner))


def test_administration_cli_never_applies_or_overwrites(
    runtime: Runtime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Exercise recursive offline planning, safe output ownership and explicit failure without accepting credential arguments.

    Args:
        runtime (Runtime): Valid synthetic enrollment bindings.
        tmp_path (Path): Disposable synthetic operator files.
        monkeypatch (pytest.MonkeyPatch): Stand in only for working-volume attestation.
        capsys (pytest.CaptureFixture[str]): Check redacted command output.

    Returns:
        None: SQL remains a review artifact; explicit existing outputs and invalid capabilities fail.
    """
    monkeypatch.setattr(administration, "require_protected", lambda _: None)
    output = tmp_path / "data.sql"
    arguments = ["native", "administration", "schema", "--kind", "data", "--role", "runtime_fixture", "--output", str(output)]
    assert cli.main(arguments) == 0
    original = output.read_bytes()
    assert output.stat().st_mode & 0o777 == 0o600
    assert cli.main(arguments) == 1 and output.read_bytes() == original
    with pytest.raises(NativeError, match="invalid"):
        provision("data", "runtime; DROP DATABASE postgres")
    value = Enrollment(runtime.access, runtime.service.authority.backend, ("read",), ("*",), 0, 4102444800)
    with pytest.raises(NativeError, match="invalid"):
        evolve(value, actions=("administrator",))
    source = tmp_path / "enrollment.json"
    source.write_text(json.dumps(as_data(value)))
    assert cli.main(["native", "administration", "enroll", "--input", str(source), "--output", str(tmp_path / "enroll.sql")]) == 0
    assert "no database changes applied" in capsys.readouterr().out
