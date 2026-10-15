"""
Validate the separation between native controller delivery policy and gateway-owned SSH credentials.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from witful.exceptions import NativeError
from witful.native.context import identifier
from witful.native.projection.bundle import prepare

if TYPE_CHECKING:
    from witful.native.config import Settings


def validate(settings: Settings) -> None:
    """
    Refuse mixed privilege roles, unreviewed protocols and gateway storage outside the explicitly protected working root.

    Args:
        settings (Settings): Complete closed deployment configuration.

    Returns:
        None: Role separation and explicit remote/attribution contracts are structurally coherent.
    """
    policy = settings.projection
    # Reuse the actual Git commit grammar to validate configured metadata before accepting any write.
    prepare(b"", "00000000-0000-0000-0000-000000000000", None, policy.author, policy.email, 0)
    if settings.role == "controller":
        if settings.gateway or (policy.mode != "disabled" and policy.permit_wrapping == settings.broker.wrapping):
            raise NativeError("denied")
        return
    if (
        not settings.gateway
        or policy.mode != "disabled"
        or policy.targets
        or settings.destinations
        or settings.archives
        or settings.derivations
        or settings.recipients
        or settings.runtime.workers != 1
    ):
        raise NativeError("denied")
    if len({item.id for item in settings.gateway}) != len(settings.gateway):
        raise NativeError("invalid")
    if not settings.probe.envelope or not Path(settings.probe.envelope).is_absolute():
        raise NativeError("invalid")
    root = Path(settings.runtime.working_directory)
    for remote in settings.gateway:
        for value in (remote.id, remote.tenant, remote.identity):
            identifier(value)
        try:
            endpoint = urlsplit(remote.url)
            if (
                endpoint.scheme != "ssh"
                or not endpoint.hostname
                or not endpoint.username
                or endpoint.password is not None
                or endpoint.query
                or endpoint.fragment
                or not endpoint.path.startswith("/")
                or endpoint.port == 0
                or not remote.url.isascii()
                or any(ord(char) < 33 or ord(char) == 127 for char in remote.url)
            ):
                raise NativeError("invalid")
        except ValueError:
            raise NativeError("invalid") from None
        if (
            not remote.ref.startswith("refs/heads/")
            or not Path(remote.ssh_key).is_absolute()
            or not Path(remote.known_hosts).is_absolute()
            or not Path(remote.directory).is_absolute()
            or not Path(remote.directory).is_relative_to(root)
            or ".." in Path(remote.directory).parts
        ):
            raise NativeError("invalid")
        prepare(b"", remote.id, None, remote.author, remote.email, 0)
