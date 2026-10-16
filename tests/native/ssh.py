"""
Own a transient loopback-only OpenSSH server with synthetic keys and no persistent account or host configuration changes.
"""

from __future__ import annotations

import os
import pwd
import shlex
import signal
import socket
import subprocess
import time
from contextlib import contextmanager
from threading import Event
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def port() -> int:
    """
    Select a currently free loopback port; subsequent listener startup still verifies successful ownership.

    Returns:
        int: Ephemeral local TCP port, with no claim that selection reserves it.
    """
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@contextmanager
def server(root: Path, remote: Path) -> Iterator[tuple[str, dict[str, str]]]:
    """
    Run the host's OpenSSH server under the current test user, with only a disposable key accepted on loopback.

    Args:
        root (Path): New private directory owned by this test.
        remote (Path): Disposable existing bare Git repository.

    Yields:
        tuple[str, dict[str, str]]: Explicit SSH URL and pinned-host transport settings; all owned processes stop on exit.
    """
    root.mkdir(mode=0o700)
    public: dict[str, str] = {}
    for name in ("host", "client"):
        key = ed25519.Ed25519PrivateKey.generate()
        path = root / name
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()))
        path.chmod(0o600)
        public[name] = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
    (root / "authorized_keys").write_text(public["client"] + "\n")
    selected = port()
    user = pwd.getpwuid(os.getuid()).pw_name
    known = root / "known_hosts"
    known.write_text(f"[127.0.0.1]:{selected} {public['host']}\n")
    configuration = root / "sshd.conf"
    configuration.write_text(
        f"ListenAddress 127.0.0.1\nPort {selected}\nHostKey {root}/host\nPidFile {root}/pid\n"
        f"AuthorizedKeysFile {root}/authorized_keys\nAllowUsers {user}\n"
        "PasswordAuthentication no\nKbdInteractiveAuthentication no\nUsePAM no\nStrictModes no\n"
        "DisableForwarding yes\nPermitTTY no\nPermitUserEnvironment no\n"
    )
    with (root / "server.log").open("wb") as log:
        process = subprocess.Popen(["/usr/sbin/sshd", "-D", "-e", "-f", str(configuration)], stdout=log, stderr=log, start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while True:
            assert process.poll() is None, (root / "server.log").read_text()
            try:
                with socket.create_connection(("127.0.0.1", selected), timeout=0.2):
                    break
            except OSError:
                assert time.monotonic() < deadline, "Synthetic SSH server did not start"
                Event().wait(0.02)
        command = shlex.join(
            (
                "ssh",
                "-F",
                "/dev/null",
                "-o",
                "BatchMode=yes",
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "IdentityAgent=none",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                f"UserKnownHostsFile={known}",
                "-i",
                str(root / "client"),
            )
        )
        yield (
            f"ssh://{user}@127.0.0.1:{selected}{remote}",
            {
                "GIT_SSH_COMMAND": command,
                "GIT_CONFIG_COUNT": "2",
                "GIT_CONFIG_KEY_0": "protocol.allow",
                "GIT_CONFIG_VALUE_0": "never",
                "GIT_CONFIG_KEY_1": "protocol.ssh.allow",
                "GIT_CONFIG_VALUE_1": "always",
            },
        )
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
