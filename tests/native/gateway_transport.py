"""
Exercise an isolated gateway through real Gunicorn mutual TLS, released broker custody and a loopback SSH Git server.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING

import psycopg
import pytest
from attrs import evolve
from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native.config import TLS, Backend, Probe, Protection, Settings
from witful.native.config import Runtime as SettingsRuntime
from witful.native.git import git
from witful.native.projection.preparation import load, prepare
from witful.native.projection.worker import transport

from tests.native.ssh import server

if TYPE_CHECKING:
    from witful.native.authority import Access
    from witful.native.config import Broker
    from witful.native.service import Service

    from tests.native.database import Databases


def exercise(service: Service, access: Access, databases: Databases, root: Path, broker: Broker) -> None:
    """
    Verify exact remote publication, peer rejection, host-key rejection, idempotent readback and bounded graceful shutdown.

    Args:
        service (Service): Source controller with an already accepted projection intent.
        access (Access): Actual source task and authority binding.
        databases (Databases): Independent synthetic grant administration.
        root (Path): Existing synthetic broker certificate directory.
        broker (Broker): Released broker endpoint with a permit-only grant for the bravo certificate.

    Returns:
        None: The real transport preserves encrypted bytes and cannot substitute client or host identity.
    """
    target = service.projection.targets[0]
    _, prepared = prepare(service, access, target.id, "Synthetic Export", "fixture@example.invalid")
    bundle, permit, envelope = load(service, access, prepared)
    fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert((root / "bravo.pem").read_text())).hexdigest()
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute(
            "INSERT INTO witful_native_grants "
            "SELECT tenant, identity_id, policy_revision, %s, %s, %s, %s, records, starts_at, expires "
            "FROM witful_native_grants WHERE id=%s",
            (target.grant, fingerprint, target.task, ["project"], access.grant),
        )
    remote = root / "remote.git"
    remote.mkdir(mode=0o700)
    git(remote, ("init", "--bare", "--template=", "."))
    working = root / "gateway-working"
    working.mkdir(mode=0o700)
    settings = Settings(
        Backend(service.authority.backend),
        TLS(
            str(root / "server.pem"),
            str(root / "server.key"),
            str(root / "ca.pem"),
            "localhost",
            str(root / "bravo.pem"),
            str(root / "bravo.key"),
        ),
        broker,
        Probe(access.scope.tenant, access.scope.identity, target.grant, target.task, access.epoch, access.policy),
        Protection("synthetic-only", "synthetic-only", "synthetic-only"),
        SettingsRuntime(working_directory=str(working), timeout=10, graceful_timeout=5),
    )
    configuration = root / "gateway.json"
    configuration.write_text(json.dumps(as_data(settings)))
    with server(root / "ssh", remote) as (url, environment), socket.socket() as listener:
        factory = root / "gateway-factory.json"
        factory.write_text(json.dumps({"authority": databases.authority, "target": target.id, "url": url, "environment": environment}))
        factory.chmod(0o600)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        selected = listener.getsockname()[1]
        selected_target = evolve(
            target,
            url=f"https://localhost:{selected}",
            ca=str(root / "ca.pem"),
            certificate=str(root / "bravo.pem"),
            key=str(root / "bravo.key"),
        )
        arguments: dict[str, object] = {
            "target": target.id,
            "operation": permit.intent.operation,
            "permit": envelope,
            "bundle": bundle.encode(service.keys(access).limits),
        }
        logs = root / "gateway.log"
        with logs.open("wb") as output:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "gunicorn",
                    "--config",
                    "python:witful.native.gunicorn",
                    "--bind",
                    f"fd://{listener.fileno()}",
                    "tests.native.live_gateway:create_app()",
                ],
                cwd=Path(__file__).resolve().parents[2],
                env={**os.environ, "WITFUL_NATIVE_CONFIG": str(configuration), "WITFUL_TEST_GATEWAY_FACTORY": str(factory)},
                pass_fds=(listener.fileno(),),
                stdout=output,
                stderr=output,
                start_new_session=True,
            )
        listener.close()
        try:
            deadline = time.monotonic() + 15
            while True:
                try:
                    response = transport(selected_target, access, arguments, service.budget.bytes)
                    break
                except NativeError as failure:
                    if failure.code != "unknown":
                        raise
                    assert process.poll() is None, logs.read_text()
                    assert time.monotonic() < deadline, logs.read_text()
                    Event().wait(0.05)
            assert response == {
                "state": "remote_verified",
                "operation": permit.intent.operation,
                "target": target.id,
                "generation": permit.intent.generation,
                "oid": prepared.oid,
            }
            denied = evolve(selected_target, certificate=str(root / "alpha.pem"), key=str(root / "alpha.key"))
            with pytest.raises(NativeError, match="denied"):
                transport(denied, access, arguments, service.budget.bytes)
            # An unknown host must fail even for an already-published candidate; no local receipt substitutes for independent readback.
            known = root / "ssh/known_hosts"
            trusted = known.read_bytes()
            known.write_bytes(b"")
            with pytest.raises(NativeError, match="unknown"):
                transport(selected_target, access, arguments, service.budget.bytes)
            known.write_bytes(trusted)
            assert transport(selected_target, access, arguments, service.budget.bytes) == response
            assert git(remote, ("rev-parse", "refs/heads/projection")).strip().decode() == prepared.oid
            assert b"synthetic-native-canary" not in git(remote, ("cat-file", "blob", prepared.oid + ":native.cbor"))
            os.killpg(process.pid, signal.SIGTERM)
            assert process.wait(timeout=7) == 0
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        assert b"synthetic-native-canary" not in logs.read_bytes()
