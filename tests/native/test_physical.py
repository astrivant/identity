"""
Exercise actual physical restore, synchronous standby failover and ciphertext inspection on disposable synthetic PostgreSQL clusters.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from threading import Event
from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from attrs import evolve
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from witful.exceptions import NativeError
from witful.native.administration import Enrollment, enrollment
from witful.native.authority import Access, Authority
from witful.native.backup import Archive, verify
from witful.native.postgres import Postgres
from witful.native.service import Service
from witful.native.storage import Scope

from tests.native.database import isolated
from tests.native.physical import ROOT, cluster, docker, sql
from tests.native.runtime import lesson

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from tests.native.conftest import Fixture


def eventually(check: Callable[[], bool]) -> None:
    """
    Poll an actual bounded infrastructure condition rather than treating a sleep duration as evidence.

    Args:
        check (Callable[[], bool]): Side-effect-free observation.

    Returns:
        None: The observed condition holds within the explicit drill deadline.
    """
    deadline = time.monotonic() + 40
    while not check():
        if time.monotonic() >= deadline:
            raise AssertionError("Synthetic recovery condition timed out")
        Event().wait(0.1)


def observed(url: str, query: str) -> object:
    """
    Read one actual drill condition on a short-lived administrative connection.

    Args:
        url (str): Invocation-owned synthetic database.
        query (str): Test-owned observation SQL, never user input.

    Returns:
        object: First scalar observation.
    """
    with psycopg.connect(url, autocommit=True, connect_timeout=3) as connection:
        row = connection.execute(query).fetchone()
    assert row is not None
    return row[0]


@pytest.mark.skipif(os.environ.get("WITFUL_NATIVE_PHYSICAL_TESTS") != "1", reason="Explicit disposable Docker physical drill")
def test_physical_restore_and_acknowledged_synchronous_failover(fixture: Fixture, tmp_path: Path) -> None:
    """
    Recover encrypted records from a verified base backup/WAL target and preserve every synchronous acknowledgment after primary loss.

    Args:
        fixture (Fixture): Independent transient synthetic custody and signer pins.
        tmp_path (Path): Disposable synthetic configuration, reports and decompressed backup views.

    Returns:
        None: Selected PITR frontier, zero acknowledged failover loss, stale-epoch denial and decoded storage checks pass.
    """
    with cluster(tmp_path) as drill, isolated(drill.connection("primary"), cleanup=False) as databases:
        access = Access(Scope(str(uuid4()), str(uuid4())), "a" * 64, str(uuid4()), str(uuid4()), 1, str(uuid4()))
        backend = str(uuid4())
        # Enrollment contains its own transaction; ordinary runtime writes still use driver-owned transactions.
        with psycopg.connect(databases.authority_admin, autocommit=True) as connection:
            connection.execute(enrollment(Enrollment(access, backend, ("read", "traverse", "write", "export"), ("*",), 0, 4102444800)))
        service = Service(Postgres(databases.data), Authority(databases.authority, backend), lambda _: fixture.service, lambda: None)
        canary = "synthetic-physical-canary-" + uuid4().hex
        first = service.append(access, str(uuid4()), "main", None, (lesson(canary + "-one"),))
        primary = drill.container("primary")
        docker(
            "exec",
            "--user",
            "postgres",
            primary,
            "pg_basebackup",
            "-U",
            "postgres",
            "-D",
            "/drill/base",
            "-X",
            "stream",
            "--checkpoint=fast",
        )
        docker("exec", "--user", "postgres", primary, "pg_verifybackup", "/drill/base")
        hba = docker("exec", primary, "cat", "/data/pg_hba.conf").decode()
        drill.file("primary-hba.conf", hba + "\nhost replication postgres 0.0.0.0/0 scram-sha-256\n", "/data/pg_hba.conf")
        with psycopg.connect(drill.connection("primary"), autocommit=True) as admin:
            admin.execute(sql("reload"))
        drill.copy("standby")
        docker(
            "run",
            "--rm",
            "--network=none",
            "--volume",
            drill.container("standby") + ":/data",
            "--entrypoint",
            "touch",
            drill.image,
            "/data/standby.signal",
        )
        drill.file(
            "standby.conf",
            "include='/data/postgresql.conf'\ndata_directory='/data'\nlisten_addresses='*'\nhot_standby=on\n"
            + f"primary_conninfo='host={primary} port=5432 user=postgres password=fixture application_name=native_drill sslmode=disable'\n",
            "/drill/standby.conf",
        )
        drill.start("standby", "/drill/standby.conf")
        primary_url = drill.connection("primary")
        eventually(lambda: observed(primary_url, sql("streaming")) == 1)
        with psycopg.connect(primary_url, autocommit=True) as admin:
            admin.execute(sql("require-standby"))
            admin.execute(sql("reload"))
        eventually(lambda: observed(primary_url, sql("synchronous")) == 1)
        service = evolve(service, store=Postgres(databases.data, synchronous=True))
        previous = service.history(access, "main")[-1][0].id
        middle = service.append(access, str(uuid4()), "main", previous, (lesson(canary + "-two"),))
        with psycopg.connect(primary_url, autocommit=True) as admin:
            admin.execute(sql("restore-point"))
        previous = service.history(access, "main")[-1][0].id
        final = service.append(access, str(uuid4()), "main", previous, (lesson(canary + "-three"),))
        history = service.store.history(access.scope)
        with psycopg.connect(primary_url, autocommit=True) as admin:
            row = admin.execute(sql("segment")).fetchone()
            assert row is not None and isinstance(row[0], str)
            segment = row[0]
            admin.execute(sql("switch"))
        eventually(lambda: observed(primary_url, sql("archive")) == segment)
        # Killing the sole primary is the physical fence. Promotion must precede any new accepted writes.
        started = time.monotonic()
        docker("kill", "--signal=KILL", primary)
        docker("exec", "--user", "postgres", drill.container("standby"), "pg_ctl", "promote", "-D", "/data", "-w")
        standby_url = drill.connection("standby")
        eventually(lambda: observed(standby_url, sql("recovering")) is False)
        standby_port = conninfo_to_dict(standby_url)["port"]
        promoted = evolve(
            service,
            store=Postgres(make_conninfo(databases.data, port=standby_port)),
            authority=Authority(make_conninfo(databases.authority, port=standby_port), backend),
        )
        assert promoted.store.history(access.scope) == history
        assert promoted.authority.check(access, "read", "*", int(time.time())).head == history[-1].target
        verify(promoted, access, Archive(access.scope, history))
        failover_seconds = time.monotonic() - started
        with psycopg.connect(make_conninfo(databases.authority_admin, port=standby_port)) as admin:
            admin.execute(
                sql("advance-epoch"),
                (access.scope.tenant, access.scope.identity),
            )
        with pytest.raises(NativeError, match="conflict"):
            promoted.history(access, "main")
        current = evolve(access, epoch=2)
        promoted.append(current, str(uuid4()), "main", promoted.history(current, "main")[-1][0].id, (lesson(canary + "-after-failover"),))
        # Recover a distinct inactive cluster to the explicit earlier frontier, never routing it over newer accepted state.
        drill.copy("restore")
        docker(
            "run",
            "--rm",
            "--network=none",
            "--volume",
            drill.container("restore") + ":/data",
            "--entrypoint",
            "touch",
            drill.image,
            "/data/recovery.signal",
        )
        restore_config = (
            "include='/data/postgresql.conf'\ndata_directory='/data'\nlisten_addresses='*'\n"
            "restore_command='cp /drill/wal/%f %p'\nrecovery_target_name='native_reviewed_frontier'\nrecovery_target_action='promote'\n"
        )
        # The old primary is stopped; write recovery configuration through the surviving drill-volume owner.
        local = tmp_path / "restore.conf"
        local.write_text(restore_config)
        docker("cp", str(local), drill.container("standby") + ":/drill/restore.conf")
        docker("exec", "--user", "0", drill.container("standby"), "chmod", "644", "/drill/restore.conf")
        started = time.monotonic()
        drill.start("restore", "/drill/restore.conf")
        restore_url = drill.connection("restore")
        eventually(lambda: observed(restore_url, sql("recovering")) is False)
        restore_port = conninfo_to_dict(restore_url)["port"]
        restored = evolve(
            service,
            store=Postgres(make_conninfo(databases.data, port=restore_port)),
            authority=Authority(make_conninfo(databases.authority, port=restore_port), backend),
        )
        assert restored.store.history(access.scope) == history[:2]
        assert restored.authority.check(access, "read", "*", int(time.time())).head == history[1].target
        verify(restored, access, Archive(access.scope, history[:2]))
        assert len(restored.history(access, "main")) == 2
        recovery_seconds = time.monotonic() - started
        # Parse archived WAL and decompress full-page images; restore/pg_dump inspect the reconstructed TOAST-visible tuples too.
        target = drill.container("restore")
        docker("exec", "--user", "postgres", target, "mkdir", "/drill/fullpages")
        docker(
            "exec",
            "--user",
            "postgres",
            target,
            "pg_waldump",
            "--path=/drill/wal",
            "--save-fullpage=/drill/fullpages",
            "--quiet",
            segment,
            segment,
        )
        pages = tmp_path / "pages"
        docker("cp", target + ":/drill/fullpages", str(pages))
        assert any(pages.iterdir())
        assert all(canary.encode() not in path.read_bytes() for path in pages.iterdir())
        database_name = conninfo_to_dict(databases.data)["dbname"]
        assert isinstance(database_name, str)
        docker("exec", "--user", "postgres", target, "pg_dump", "-U", "postgres", "-Fc", "-f", "/drill/data.dump", database_name)
        decoded = docker("exec", "--user", "postgres", target, "pg_restore", "--file=-", "/drill/data.dump")
        assert canary.encode() not in decoded
        with psycopg.connect(make_conninfo(databases.data_admin, port=restore_port)) as admin:
            admin.execute(sql("positive-control"))
            admin.execute(sql("insert-control"), ("decoded-positive-control-" * 20000,))
            assert admin.execute(sql("control-length")).fetchone() == (500000,)
        docker(
            "exec",
            "--user",
            "postgres",
            target,
            "pg_dump",
            "-U",
            "postgres",
            "-Fc",
            "-t",
            "physical_positive_control",
            "-f",
            "/drill/control.dump",
            database_name,
        )
        control = docker("exec", "--user", "postgres", target, "pg_restore", "--file=-", "/drill/control.dump")
        assert b"decoded-positive-control-" * 100 in control
        report = {
            "schema": 1,
            "image": drill.image,
            "base_generation": first.generation,
            "pitr_generation": middle.generation,
            "acknowledged_generation": final.generation,
            "failover_acknowledged_loss": 0,
            "pitr_excluded_later_operations": 1,
            "failover_seconds": failover_seconds,
            "pitr_seconds": recovery_seconds,
            "decoded_wal_fullpages": len(tuple(pages.iterdir())),
            "decoded_custom_backup": True,
            "positive_toast_control": True,
            "scope": "synthetic local Docker; independent keys in test memory; no production disk/swap attestation",
        }
        inputs = (
            sorted((ROOT / "pkg/witful/native").rglob("*.py"))
            + sorted((ROOT / "pkg/witful/sql/postgres/native").rglob("*.sql"))
            + sorted((ROOT / "tests/native/resources/physical").iterdir())
            + [
                ROOT / "tests/native/test_physical.py",
                ROOT / "tests/native/physical.py",
                ROOT / "tests/native/database.py",
                ROOT / "poetry.lock",
                ROOT / ".github/workflows/ci.yml",
            ]
        )
        report["base_revision"] = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, check=True, text=True
        ).stdout.strip()
        report["source_digests"] = {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs if path.is_file()
        }
        report["source_binding"] = "Actual input digests are authoritative; a local base revision may precede uncommitted edits"
        destination = os.environ.get("WITFUL_NATIVE_EVIDENCE")
        if destination:
            from pathlib import Path

            Path(destination).mkdir(parents=True, exist_ok=True)
            (Path(destination) / "physical.json").write_text(json.dumps(report, indent=2) + "\n")
    for role in ("primary", "standby", "restore"):
        assert canary.encode() not in (tmp_path / (role + ".log")).read_bytes()
