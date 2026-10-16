"""
Keep optional microservice working sets bounded and require current controller authorization on every hit.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections import OrderedDict
from threading import Lock
from typing import TYPE_CHECKING, Protocol

from attrs import field, frozen, mutable

from witful.exceptions import NativeError
from witful.native import codec, domains
from witful.native.context import identifier
from witful.native.wire import mapping, text

if TYPE_CHECKING:
    from collections.abc import Callable

    from witful.native.authority import Access
    from witful.native.domains import Entry
    from witful.native.service import Service

__all__ = ["Limits", "Reader", "conditional_read"]


@frozen
class Limits:
    """
    Bound optional plaintext memory retention independently of request and controller limits.

    Attributes:
        entries (int): Maximum entries; zero disables retention by default.
        bytes (int): Maximum aggregate encoded payload bytes.
        response_bytes (int): Maximum encoded response size, independent of retained-byte capacity.
        seconds (float): Retention lifetime, never an authorization lease.
    """

    entries: int = 0
    bytes: int = 4 * 1024 * 1024
    response_bytes: int = 64 * 1024 * 1024
    seconds: float = 30.0

    def __attrs_post_init__(self) -> None:
        """
        Reject negative or nonfinite configuration before any read.

        Returns:
            None: Limits define a finite optional working set.
        """
        if type(self.entries) is not int or self.entries < 0 or type(self.bytes) is not int or self.bytes < 1:
            raise NativeError("invalid")
        if type(self.response_bytes) is not int or self.response_bytes < 1:
            raise NativeError("invalid")
        if not math.isfinite(self.seconds) or self.seconds <= 0:
            raise NativeError("invalid")


class Transport(Protocol):
    """
    Describe the authenticated client's existing bounded operation boundary.
    """

    def invoke(self, operation: str, arguments: object) -> object:
        """
        Execute one authenticated controller operation.

        Args:
            operation (str): Package-owned operation name.
            arguments (object): Closed operation input.

        Returns:
            object: Verified binary response or a fail-closed domain error.
        """
        ...


@frozen
class Cached:
    """
    Retain immutable encoded values, not caller-mutable domain dictionaries.

    Attributes:
        token (str): Opaque current authorization, frontier and representation binding.
        value (bytes): Encoded domain record in protected process memory only.
        expires (float): Local monotonic retention deadline.
    """

    token: str
    value: bytes = field(repr=False)
    expires: float


def conditional_read(service: Service, access: Access, record: str, token: str | None) -> dict[str, object]:
    """
    Validate current custody and result-release permission even when the client already has a matching representation.

    Args:
        service (Service): Protected native runtime.
        access (Access): Verified certificate and current scope/grant bindings.
        record (str): Immutable logical revision UUID.
        token (str | None): Previously returned opaque conditional token.

    Returns:
        dict[str, object]: Current token plus a complete domain record, or null only for an authorized unchanged response.
    """
    started = service.monotonic()
    registration, frontier = service.snapshot(access, "read", identifier(record))
    revision = service.revision(access, frontier, record)
    entry = domains.decode(service.open(access, revision.payload))
    if entry.domain != revision.domain:
        raise NativeError("invalid")
    # Bind the authenticated peer and every authority/representation boundary. TTL never substitutes for this server check.
    current = hashlib.sha256(
        codec.encode(
            [
                "witful-conditional-read-v1",
                access.scope.tenant,
                access.scope.identity,
                access.subject,
                access.grant,
                access.task,
                access.epoch,
                access.policy,
                record,
                registration.backend,
                registration.head.digest,
                revision.payload.digest,
            ]
        )
    ).hexdigest()
    service.release(access, "read", record, registration, started)
    return {"token": current, "entry": None if token == current else domains.encode(entry)}


@mutable
class Reader:
    """
    Reuse bounded local payloads only after a successful current controller response; never acknowledge writes or spill to disk.

    Attributes:
        client (Transport): Verified request transport, normally native.client.Client.
        protection (Callable[[], None]): Mandatory current process-memory/core-dump/storage protection check.
        limits (Limits): Optional retention policy, disabled by default.
        monotonic (Callable[[], float]): Injectable retention clock.
    """

    client: Transport = field(repr=False)
    protection: Callable[[], None] = field(repr=False)
    limits: Limits = Limits()
    monotonic: Callable[[], float] = time.monotonic
    _items: OrderedDict[str, Cached] = field(factory=OrderedDict, init=False, repr=False)
    _lock: Lock = field(factory=Lock, init=False, repr=False)

    def clear(self) -> None:
        """
        Drop all references after failure, reconfiguration or explicit workload shutdown.

        Returns:
            None: The cache is empty; Python object release is not a secure memory-erasure promise.
        """
        with self._lock:
            self._items.clear()

    def read(self, record: str) -> Entry:
        """
        Obtain a freshly authorized immutable domain result while keeping only a bounded protected working set.

        Args:
            record (str): Exact logical revision UUID.

        Returns:
            Entry: A newly decoded value; caller mutations cannot change cached bytes.
        """
        try:
            self.protection()
            identifier(record)
            now = self.monotonic()
            with self._lock:
                expired = [key for key, item in self._items.items() if item.expires <= now]
                for key in expired:
                    del self._items[key]
                cached = self._items.get(record) if self.limits.entries else None
            result = mapping(
                self.client.invoke("read-conditional", {"record": record, "token": cached.token if cached else None}), {"token", "entry"}
            )
            token = text(result["token"])
            if result["entry"] is None:
                if cached is None or token != cached.token:
                    raise NativeError("invalid")
                encoded = cached.value
                entry = domains.decode(codec.decode(encoded, codec.Limits(bytes=self.limits.bytes)))
            else:
                entry = domains.decode(result["entry"])
                encoded = codec.encode(result["entry"], codec.Limits(bytes=self.limits.response_bytes))
            self.protection()
            with self._lock:
                self._items.pop(record, None)
                if self.limits.entries and len(encoded) <= self.limits.bytes:
                    while self._items and (
                        len(self._items) >= self.limits.entries
                        or sum(len(item.value) for item in self._items.values()) + len(encoded) > self.limits.bytes
                    ):
                        self._items.popitem(last=False)
                    self._items[record] = Cached(token, encoded, self.monotonic() + self.limits.seconds)
            return entry
        except Exception:
            # No offline stale fallback after denial, key outage, transport loss or protection failure.
            self.clear()
            raise

    def status(self) -> dict[str, int]:
        """
        Report bounded local occupancy without identities, labels, queries or content fingerprints.

        Returns:
            dict[str, int]: Aggregate retained entry and byte counts for an owning microservice's metrics.
        """
        with self._lock:
            return {"entries": len(self._items), "bytes": sum(len(item.value) for item in self._items.values())}
