"""
Own disposable PostgreSQL primary, synchronous standby and PITR containers for explicit synthetic acceptance drills.
"""

from __future__ import annotations

import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import yaml
from attrs import frozen
from psycopg.conninfo import make_conninfo

if TYPE_CHECKING:
    from collections.abc import Iterator

ROOT = Path(__file__).resolve().parents[2]


def sql(name: str) -> str:
    """
    Load independently linted test-only PostgreSQL statements.

    Args:
        name (str): Internal fixture resource name.

    Returns:
        str: SQL text with driver placeholders retained where required.
    """
    return (ROOT / "tests/native/resources/physical" / (name + ".sql")).read_text()


def docker(*arguments: str, seconds: int = 90) -> bytes:
    """
    Execute one bounded Docker test operation and retain its diagnostics only on failure.

    Args:
        *arguments (str): Fixed test commands and invocation-owned resource identifiers.
        seconds (int): Complete command deadline.

    Returns:
        bytes: Captured stdout, with no production credentials or private payloads involved.
    """
    return subprocess.run(["docker", *arguments], check=True, capture_output=True, timeout=seconds).stdout


@frozen
class Drill:
    """
    Track only this test's Docker resources and the workflow's authoritative pinned PostgreSQL image.

    Attributes:
        name (str): Unique resource namespace.
        image (str): Same immutable image as ordinary native CI tests.
        working (Path): Synthetic configuration and verification evidence directory.
    """

    name: str
    image: str
    working: Path

    def container(self, role: str) -> str:
        """
        Resolve a test-owned process name.

        Args:
            role (str): Primary, standby or restore responsibility.

        Returns:
            str: Unique Docker container name.
        """
        return self.name + "-" + role

    def connection(self, role: str) -> str:
        """
        Resolve the actual loopback port assigned by Docker, without selecting a racy free port.

        Args:
            role (str): Running test container.

        Returns:
            str: Synthetic PostgreSQL administrator URL.
        """
        port = docker("port", self.container(role), "5432/tcp").decode().strip().rsplit(":", 1)[1]
        return make_conninfo(host="127.0.0.1", port=port, user="postgres", password="fixture", dbname="postgres", sslmode="disable")

    def wait(self, role: str) -> None:
        """
        Wait for bounded actual database readiness, preserving a failed startup as a test failure.

        Args:
            role (str): Running test container.

        Returns:
            None: A real SQL connection succeeds within the deadline.
        """
        deadline = time.monotonic() + 40
        while True:
            try:
                with psycopg.connect(self.connection(role), connect_timeout=2):
                    return
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise
                Event().wait(0.1)

    def file(self, name: str, payload: str, destination: str) -> None:
        """
        Copy synthetic test configuration into an explicitly owned disposable container path.

        Args:
            name (str): Local synthetic filename.
            payload (str): Reviewed fixture configuration, never actual credentials.
            destination (str): Explicit test-owned configuration path in the primary or shared drill volume.

        Returns:
            None: The copied file is readable by the unprivileged PostgreSQL process.
        """
        path = self.working / name
        path.write_text(payload)
        docker("cp", str(path), self.container("primary") + ":" + destination)
        docker("exec", "--user", "0", self.container("primary"), "chown", "postgres:postgres", destination)
        docker("exec", "--user", "0", self.container("primary"), "chmod", "600", destination)

    def copy(self, role: str) -> None:
        """
        Populate a fresh owned data volume from the verified physical base backup.

        Args:
            role (str): New standby or restore volume.

        Returns:
            None: Only this invocation's empty target receives the original backup bytes.
        """
        docker(
            "run",
            "--rm",
            "--network=none",
            "--user",
            "0",
            "--volume",
            self.name + "-drill:/drill:ro",
            "--volume",
            self.container(role) + ":/target",
            "--entrypoint",
            "cp",
            self.image,
            "-a",
            "/drill/base/.",
            "/target/",
        )

    def start(self, role: str, configuration: str | None = None) -> None:
        """
        Start an isolated cluster with a persistent disposable volume and no public listener.

        Args:
            role (str): Explicit test responsibility.
            configuration (str | None): Reviewed recovery or standby configuration in the shared drill volume.

        Returns:
            None: The container is running; callers separately verify database readiness and recovery state.
        """
        arguments = [
            "run",
            "--detach",
            "--name",
            self.container(role),
            "--network",
            self.name,
            "--publish",
            "127.0.0.1::5432",
            "--env",
            "POSTGRES_PASSWORD=fixture",
            "--env",
            "PGDATA=/data",
            "--volume",
            self.container(role) + ":/data",
            "--volume",
            self.name + "-drill:/drill",
            self.image,
            "postgres",
            "-c",
            "wal_level=replica",
        ]
        if role == "primary":
            arguments += ["-c", "archive_mode=on", "-c", "archive_command=/bin/sh /drill/archive.sh %p %f"]
        if configuration is not None:
            arguments += ["-c", "config_file=" + configuration, "-c", "hba_file=/data/pg_hba.conf"]
        docker(*arguments)
        self.wait(role)


@contextmanager
def cluster(working: Path) -> Iterator[Drill]:
    """
    Allocate uniquely named local test infrastructure and always remove exactly those containers, volumes and network.

    Args:
        working (Path): Existing disposable synthetic evidence directory.

    Yields:
        Drill: Ready primary; no real collection, production credentials or host database is modified.
    """
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    image = workflow["jobs"]["tests"]["services"]["postgres"]["image"]
    assert isinstance(image, str) and "@sha256:" in image
    drill = Drill("witful-physical-" + uuid4().hex[:12], image, working)
    docker("network", "create", drill.name)
    try:
        for role in ("primary", "standby", "restore", "drill"):
            docker("volume", "create", drill.container(role))
        drill.start("primary")
        docker("exec", "--user", "0", drill.container("primary"), "mkdir", "-p", "/drill/wal")
        docker("exec", "--user", "0", drill.container("primary"), "chown", "-R", "postgres:postgres", "/drill")
        drill.file("archive.sh", (ROOT / "tests/native/resources/physical/archive.sh").read_text(), "/drill/archive.sh")
        yield drill
    finally:
        for role in ("restore", "standby", "primary"):
            result = subprocess.run(["docker", "logs", drill.container(role)], capture_output=True, timeout=15, check=False)
            payload = result.stdout + result.stderr
            (working / (role + ".log")).write_bytes(payload)
            evidence = os.environ.get("WITFUL_NATIVE_EVIDENCE")
            if evidence:
                output = Path(evidence)
                output.mkdir(parents=True, exist_ok=True)
                (output / (role + ".log")).write_bytes(payload)
        for role in ("restore", "standby", "primary"):
            subprocess.run(["docker", "rm", "--force", drill.container(role)], capture_output=True, timeout=30, check=False)
        for role in ("restore", "standby", "primary", "drill"):
            subprocess.run(["docker", "volume", "rm", drill.container(role)], capture_output=True, timeout=30, check=False)
        docker("network", "rm", drill.name)
