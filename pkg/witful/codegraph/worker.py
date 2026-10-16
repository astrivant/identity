"""
Run the optional locked SDK in a bounded disposable no-network container.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import TYPE_CHECKING
from uuid import uuid4

from attrs import frozen

from witful.codegraph.models import Edge, Enrollment, Node  # noqa: TC001 - Runtime schema resolution.
from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native.models import parse

if TYPE_CHECKING:
    from witful.codegraph.snapshot import Snapshot


@frozen
class Extraction:
    """
    Admit only inert bounded SDK projections from the isolated worker.

    Attributes:
        nodes (tuple[Node, ...]): Qualified symbols from approved source paths.
        edges (tuple[Edge, ...]): Extracted graph relationships.
        indexer (str): Worker-reported package version, bound also by the enrolled image digest.
        unresolved (int): Known unresolved references.
    """

    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    indexer: str
    unresolved: int


def extract(enrollment: Enrollment, snapshot: Snapshot) -> Extraction:
    """
    Own container lifetime, temporary SQLite files, output limits and cancellation cleanup.

    Args:
        enrollment (Enrollment): Signed admission settings including an immutable local image ID.
        snapshot (Snapshot): Exact approved Python inputs; no host directory is mounted.

    Returns:
        Extraction: Complete inert graph or a redacted failure; partial output is never published.
    """
    name = "witful-codegraph-" + uuid4().hex
    environment = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": os.environ.get("HOME", "/"),
        "DOCKER_HOST": "unix:///var/run/docker.sock",
    }
    # The Docker daemon is part of the admitted host. Remote Docker contexts are deliberately unsupported.
    arguments = [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--name",
        name,
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=64",
        "--ulimit",
        "core=0",
        "--memory",
        f"{enrollment.memory_mb}m",
        "--memory-swap",
        f"{enrollment.memory_mb}m",
        "--tmpfs",
        f"/work:rw,nosuid,nodev,noexec,size={enrollment.memory_mb}m,uid=1000,gid=1000,mode=0700",
        "--user",
        "1000:1000",
        "--log-driver=none",
        "--interactive",
        enrollment.image,
        "/usr/bin/timeout",
        "--signal=TERM",
        "--kill-after=5",
        str(enrollment.seconds),
        "node",
        "/opt/codegraph/worker.mjs",
    ]
    raw = json.dumps({"sources": [as_data(source) for source in snapshot.sources]}, ensure_ascii=True).encode()
    if len(raw) > 16 * 1024 * 1024:
        raise NativeError("incomplete")
    try:
        result = subprocess.run(arguments, input=raw, capture_output=True, timeout=enrollment.seconds + 10, check=False, env=environment)
        if result.returncode or len(result.stdout) > 16 * 1024 * 1024:
            raise NativeError("incomplete")
        return parse(json.loads(result.stdout), Extraction)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise NativeError("unavailable") from None
    finally:
        # Removing the CLI process alone can orphan a daemon-owned worker after timeout or interruption.
        try:
            cleanup = subprocess.run(["docker", "rm", "--force", name], env=environment, capture_output=True, timeout=15, check=False)
            if cleanup.returncode and b"No such container" not in cleanup.stderr:
                raise NativeError("unknown")
        except (OSError, subprocess.TimeoutExpired):
            raise NativeError("unknown") from None
