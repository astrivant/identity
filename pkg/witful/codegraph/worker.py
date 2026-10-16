"""
Run the optional locked SDK in a bounded disposable no-network container.
"""

from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import time
from typing import TYPE_CHECKING
from uuid import uuid4

from attrs import frozen

from witful.codegraph.models import Edge, Enrollment, File, Node  # noqa: TC001 - Runtime schema resolution.
from witful.exceptions import NativeError
from witful.knowledge.contracts import as_data
from witful.native.models import parse

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

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
        files (tuple[File, ...]): SDK-owned detection and coverage for every selected text input.
    """

    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    indexer: str
    unresolved: int
    files: tuple[File, ...] = ()


def run(arguments: Sequence[str], data: bytes, environment: Mapping[str, str], seconds: float, limit: int) -> bytes:
    """
    Bound worker output while receiving it and always reap the owned process group.

    Args:
        arguments (Sequence[str]): Reviewed executable and literal arguments.
        data (bytes): Bounded transient source request.
        environment (Mapping[str, str]): Closed process environment.
        seconds (float): Maximum complete exchange duration.
        limit (int): Maximum response bytes admitted while reading.

    Returns:
        bytes: Complete successful response, never partial output or diagnostics.
    """
    deadline = time.monotonic() + seconds
    pending = memoryview(data)
    output = bytearray()
    with subprocess.Popen(
        arguments,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=environment,
        start_new_session=True,
        bufsize=0,
    ) as process:
        assert process.stdin is not None and process.stdout is not None
        try:
            with selectors.DefaultSelector() as selector:
                os.set_blocking(process.stdin.fileno(), False)
                os.set_blocking(process.stdout.fileno(), False)
                selector.register(process.stdout, selectors.EVENT_READ)
                if pending:
                    selector.register(process.stdin, selectors.EVENT_WRITE)
                else:
                    process.stdin.close()
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise NativeError("incomplete")
                    for key, _ in selector.select(min(remaining, 0.25)):
                        if key.fileobj is process.stdin:
                            written = os.write(process.stdin.fileno(), pending[:65536])
                            pending = pending[written:]
                            if not pending:
                                selector.unregister(process.stdin)
                                process.stdin.close()
                        else:
                            chunk = os.read(process.stdout.fileno(), min(65536, limit - len(output) + 1))
                            output.extend(chunk)
                            if len(output) > limit:
                                raise NativeError("incomplete")
                            if not chunk:
                                selector.unregister(process.stdout)
                if process.wait(timeout=max(0.01, deadline - time.monotonic())) != 0:
                    raise NativeError("incomplete")
                return bytes(output)
        finally:
            # Descendants can retain pipes after the direct child exits; close the whole owned group.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def extract(enrollment: Enrollment, snapshot: Snapshot) -> Extraction:
    """
    Own container lifetime, temporary SQLite files, output limits and cancellation cleanup.

    Args:
        enrollment (Enrollment): Signed admission settings including an immutable local image ID.
        snapshot (Snapshot): Exact approved UTF-8 inputs; no host directory is mounted.

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
        "--env",
        f"WITFUL_CODEGRAPH_BYTES={enrollment.worker_bytes}",
        "--env",
        f"WITFUL_CODEGRAPH_FILES={enrollment.files}",
        enrollment.image,
        "/usr/bin/timeout",
        "--signal=TERM",
        "--kill-after=5",
        str(enrollment.seconds),
        "node",
        "/opt/codegraph/worker.mjs",
    ]
    raw = json.dumps(
        {
            "sources": [as_data(source) for source in snapshot.sources],
            "extensions": {item.suffix: item.language for item in enrollment.extensions},
        },
        ensure_ascii=True,
    ).encode()
    if len(raw) > enrollment.worker_bytes:
        raise NativeError("incomplete")
    try:
        result = run(arguments, raw, environment, enrollment.seconds + 10, enrollment.worker_bytes)
        return parse(json.loads(result), Extraction)
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
