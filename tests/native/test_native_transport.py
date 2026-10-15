"""
Exercise native authentication and graceful process ownership through the actual configured Gunicorn TLS boundary.
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
from uuid import uuid4

import psycopg
import pytest
from agent_broker.testing.scenario import scenario
from attrs import evolve
from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native import domains
from witful.native.client import Client, ClientSettings
from witful.native.config import TLS, Backend, Broker, Probe, Protection, Settings, Trust
from witful.native.config import Runtime as SettingsRuntime
from witful.native.git import Git
from witful.native.postgres import Postgres
from witful.native.wire import mapping, sequence, text

from tests.native.runtime import lesson

if TYPE_CHECKING:
    from tests.native.database import Databases
    from tests.native.runtime import Runtime


def test_real_native_gunicorn_mtls_and_shutdown(runtime: Runtime, databases: Databases, tmp_path: Path) -> None:
    """
    Pass verified TLS peers into the real API, reject another issued certificate and terminate the owned process within its drain budget.

    Args:
        runtime (Runtime): Real Git or PostgreSQL source with an independent control database.
        databases (Databases): Synthetic grant administration.
        tmp_path (Path): Disposable synthetic certificates and process configuration.

    Returns:
        None: Native writes and reads cross actual TLS; shutdown leaves no owned listener or private payload diagnostics.
    """
    root = tmp_path / "native-tls"
    root.mkdir()
    access = runtime.access
    with scenario(root):
        fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert((root / "alpha.pem").read_text())).hexdigest()
        with psycopg.connect(databases.authority_admin) as admin:
            admin.execute("UPDATE witful_native_grants SET subject = %s WHERE id = %s", (fingerprint, access.grant))
        settings = Settings(
            Backend(runtime.service.authority.backend),
            TLS(
                str(root / "server.pem"),
                str(root / "server.key"),
                str(root / "ca.pem"),
                "localhost",
                str(root / "alpha.pem"),
                str(root / "alpha.key"),
            ),
            Broker(
                "https://unused.invalid",
                "unused",
                "unused",
                "unused",
                str(uuid4()),
                str(uuid4()),
                str(uuid4()),
                str(uuid4()),
                (Trust(str(uuid4()), "unused", "unused"),),
            ),
            Probe(access.scope.tenant, access.scope.identity, access.grant, access.task, access.epoch, access.policy),
            Protection("unused", "unused", "unused"),
            SettingsRuntime(working_directory=str(root), timeout=10, graceful_timeout=5),
        )
        configuration = root / "server.json"
        configuration.write_text(json.dumps(as_data(settings)))
        source = runtime.service.store
        assert isinstance(source, Git | Postgres)
        factory = root / "factory.json"
        factory.write_text(
            json.dumps(
                {
                    "kind": "git" if isinstance(source, Git) else "postgres",
                    "data": str(source.directory) if isinstance(source, Git) else databases.data,
                    "authority": databases.authority,
                    "backend": runtime.service.authority.backend,
                }
            )
        )
        factory.chmod(0o600)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        environment = {**os.environ, "WITFUL_NATIVE_CONFIG": str(configuration), "WITFUL_TEST_NATIVE_FACTORY": str(factory)}
        logs = root / "runtime.log"
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
                    "tests.native.live_app:create_app()",
                ],
                cwd=Path(__file__).resolve().parents[2],
                env=environment,
                pass_fds=(listener.fileno(),),
                stdout=output,
                stderr=output,
                start_new_session=True,
            )
        listener.close()
        client = Client(
            ClientSettings(
                f"https://localhost:{port}",
                str(root / "ca.pem"),
                str(root / "alpha.pem"),
                str(root / "alpha.key"),
                access.scope.tenant,
                access.scope.identity,
                access.grant,
                access.task,
                access.epoch,
                access.policy,
                timeout=1,
            )
        )
        arguments = {"operation": str(uuid4()), "ref": "main", "expected": None, "entries": [domains.encode(lesson())]}
        try:
            deadline = time.monotonic() + 15
            while True:
                try:
                    client.invoke("append", arguments)
                    break
                except NativeError as failure:
                    if failure.code != "unknown":
                        raise
                    assert process.poll() is None, "Synthetic Gunicorn exited before readiness"
                    if time.monotonic() >= deadline:
                        raise
                    Event().wait(0.05)
            history = sequence(client.invoke("history", {"ref": "main"}))
            item = mapping(history[0], {"revision", "entry"})
            assert domains.decode(item["entry"]) == lesson()
            revision = item["revision"]
            assert isinstance(revision, dict)
            record = text(revision["id"])
            unauthorized = Client(evolve(client.settings, certificate=str(root / "bravo.pem"), key=str(root / "bravo.key")))
            with pytest.raises(NativeError, match="denied"):
                unauthorized.invoke("read", {"record": record})
            process.terminate()
            assert process.wait(timeout=8) == 0
            with pytest.raises(NativeError, match="unknown"):
                client.invoke("read", {"record": record})
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        assert b"synthetic-native-canary" not in logs.read_bytes()
