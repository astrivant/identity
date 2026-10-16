"""
Call the native controller over mutually authenticated TLS without installing server-side key capabilities in clients.
"""

from __future__ import annotations

import json
import ssl
from http import HTTPStatus
from http.client import HTTPException, HTTPSConnection
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from attrs import frozen

from witful.exceptions import NativeCode, NativeError
from witful.native import codec
from witful.native.models import parse

if TYPE_CHECKING:
    from pathlib import Path


@frozen
class ClientSettings:
    """
    Bind one client to an explicit controller, certificate and provisioned request scope.

    Attributes:
        url (str): Controller HTTPS origin.
        ca (str): Trusted controller certificate authority.
        certificate (str): Scoped client certificate path.
        key (str): Client TLS key path.
        tenant (str): Opaque tenant UUID.
        identity (str): Opaque identity UUID.
        grant (str): Independently provisioned native and broker grant UUID.
        task (str): Authorized task UUID.
        epoch (int): Expected current backend epoch.
        policy (str): Expected native policy revision UUID.
        timeout (int): HTTP operation timeout seconds.
        max_bytes (int): Maximum request and response bytes.
    """

    url: str
    ca: str
    certificate: str
    key: str
    tenant: str
    identity: str
    grant: str
    task: str
    epoch: int
    policy: str
    timeout: int = 30
    max_bytes: int = 64 * 1024 * 1024


@frozen
class Failure:
    """
    Admit only the controller's closed redacted error vocabulary.

    Attributes:
        code (NativeCode): Stable safe diagnostic.
    """

    code: NativeCode


@frozen
class Client:
    """
    Preserve caller operation IDs and uncertain outcomes without implicit network retries.

    Attributes:
        settings (ClientSettings): Explicit endpoint, credential paths and access scope.
    """

    settings: ClientSettings

    @classmethod
    def load(cls, path: Path) -> Client:
        """
        Load bounded closed client settings without reflecting rejected values.

        Args:
            path (Path): Explicit user-owned JSON settings.

        Returns:
            Client: Typed client configuration, with transport verified on each invocation.
        """
        try:
            with path.open("rb") as stream:
                raw = stream.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise NativeError("invalid")
            settings = parse(json.loads(raw), ClientSettings)
        except (OSError, ValueError):
            raise NativeError("invalid") from None
        if min(settings.timeout, settings.max_bytes, settings.epoch) < 1:
            raise NativeError("invalid")
        return cls(settings)

    def invoke(self, operation: str, arguments: object) -> object:
        """
        Execute one bounded binary request using a real client certificate and independently verified server identity.

        Args:
            operation (str): Package-owned route operation.
            arguments (object): Closed operation-specific request data.

        Returns:
            object: Authenticated binary response, or an explicit unknown outcome after transport loss.
        """
        settings = self.settings
        connection: HTTPSConnection | None = None
        try:
            endpoint = urlsplit(settings.url)
            if (
                endpoint.scheme != "https"
                or not endpoint.hostname
                or endpoint.path not in ("", "/")
                or endpoint.username is not None
                or endpoint.password is not None
                or "?" in settings.url
                or "#" in settings.url
                or endpoint.port == 0
                or not settings.url.isascii()
                or any(ord(char) < 33 or ord(char) == 127 for char in settings.url)
            ):
                raise NativeError("invalid")
            if operation not in {
                "codegraph-build",
                "codegraph-query",
                "codegraph-recover",
                "codegraph-rotate",
                "append",
                "read",
                "read-conditional",
                "history",
                "search",
                "branch",
                "merge",
                "derive",
                "project-deliver",
                "project-probe",
                "project-drain",
                "project-status",
                "project-check",
                "recover",
                "migrate",
                "migration-abort",
                "rotate",
                "export",
                "share",
                "restore",
                "original-capture",
                "original-list",
                "original-restore",
            }:
                raise NativeError("unsupported")
            context = ssl.create_default_context(cafile=settings.ca)
            context.minimum_version = ssl.TLSVersion.TLSv1_3
            context.load_cert_chain(settings.certificate, settings.key)
            access = {
                "tenant": settings.tenant,
                "identity": settings.identity,
                "grant": settings.grant,
                "task": settings.task,
                "epoch": settings.epoch,
                "policy": settings.policy,
            }
            limits = codec.Limits(bytes=settings.max_bytes)
            payload = codec.encode({"access": access, "arguments": arguments}, limits)
            connection = HTTPSConnection(endpoint.hostname, endpoint.port or 443, context=context, timeout=settings.timeout)
            connection.request("POST", "/v1/" + operation, payload, {"Content-Type": "application/cbor"})
            response = connection.getresponse()
            raw = response.read(settings.max_bytes + 1)
            if len(raw) > settings.max_bytes:
                raise NativeError("incomplete")
            if response.getheader("Content-Type", "").split(";", 1)[0] != "application/cbor":
                raise NativeError("unknown")
            result = codec.decode(raw, limits)
            if response.status != HTTPStatus.OK:
                raise NativeError(parse(result, Failure).code)
            return result
        except (OSError, HTTPException, ValueError):
            raise NativeError("unknown") from None
        finally:
            if connection is not None:
                connection.close()
