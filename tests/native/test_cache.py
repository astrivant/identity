"""
Verify current authorization, representation invalidation and bounded immutable client memory without real private records.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from attrs import frozen
from witful.exceptions import NativeError
from witful.native.cache import Limits, Reader, conditional_read
from witful.native.rotation import rotate
from witful.native.wire import mapping, text

from tests.native.runtime import lesson

if TYPE_CHECKING:
    from tests.native.conftest import Fixture
    from tests.native.database import Databases
    from tests.native.runtime import Runtime


@frozen
class Transport:
    """
    Observe real conditional service responses while injecting only the authenticated transport boundary.

    Attributes:
        runtime (Runtime): Actual native store and authority.
        reused (list[bool]): Whether each server response omitted already-held domain bytes.
    """

    runtime: Runtime
    reused: list[bool]

    def invoke(self, operation: str, arguments: object) -> object:
        """
        Execute the same fresh conditional read used by the API.

        Args:
            operation (str): Required conditional-read name.
            arguments (object): Closed logical-record/token input.

        Returns:
            object: Actual current service result.
        """
        assert operation == "read-conditional"
        args = mapping(arguments, {"record", "token"})
        result = conditional_read(
            self.runtime.service, self.runtime.access, text(args["record"]), None if args["token"] is None else text(args["token"])
        )
        self.reused.append(result["entry"] is None)
        return result


def test_cache_authorizes_every_hit_and_invalidates_rotation(runtime: Runtime, databases: Databases) -> None:
    """
    Reuse bytes only while the exact authorized representation remains current, and clear memory after revocation.

    Args:
        runtime (Runtime): Real native source and authority.
        databases (Databases): Independently administered synthetic grant store.

    Returns:
        None: Revoked access never falls back to a previously cached result.
    """
    service, access = runtime.service, runtime.access
    service.append(access, str(uuid4()), "main", None, (lesson(),))
    record = service.history(access, "main")[0][0].id
    transport = Transport(runtime, [])
    reader = Reader(transport, lambda: None, Limits(entries=2))
    first = reader.read(record)
    assert reader.read(record) == first
    assert transport.reused == [False, True]
    rotate(service, access, str(uuid4()), "reseal")
    assert reader.read(record) == first
    assert transport.reused == [False, True, False]
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute("DELETE FROM witful_native_grants WHERE id = %s", (access.grant,))
    with pytest.raises(NativeError, match="denied"):
        reader.read(record)
    assert reader.status() == {"entries": 0, "bytes": 0}


def test_cache_key_outage_never_returns_old_plaintext(runtime: Runtime, fixture: Fixture) -> None:
    """
    Require current key-custody availability even for a locally retained matching value.

    Args:
        runtime (Runtime): Real native source.
        fixture (Fixture): Independent synthetic key service.

    Returns:
        None: Missing custody fails closed and releases all cache references.
    """
    service, access = runtime.service, runtime.access
    service.append(access, str(uuid4()), "main", None, (lesson(),))
    record = service.history(access, "main")[0][0].id
    reader = Reader(Transport(runtime, []), lambda: None, Limits(entries=2))
    reader.read(record)
    fixture.keys.wrapping.clear()
    with pytest.raises(NativeError, match="unavailable"):
        reader.read(record)
    assert reader.status()["entries"] == 0


def test_cache_limits_defaults_expiry_and_caller_mutation(runtime: Runtime) -> None:
    """
    Keep opt-in retention independent of successful reads, and isolate caller-owned dictionaries from stored bytes.

    Args:
        runtime (Runtime): Actual service and test grant.

    Returns:
        None: Capacity, TTL, disabled defaults and immutable storage behavior hold.
    """
    service, access = runtime.service, runtime.access
    service.append(access, str(uuid4()), "main", None, (lesson("first"), lesson("second")))
    first, second = [revision.id for revision, _ in service.history(access, "main")]
    transport = Transport(runtime, [])
    disabled = Reader(transport, lambda: None)
    disabled.read(first)
    disabled.read(first)
    assert disabled.status()["entries"] == 0 and transport.reused == [False, False]
    clock = [0.0]
    reader = Reader(transport, lambda: None, Limits(entries=1, seconds=1), lambda: clock[0])
    entry = reader.read(first)
    assert isinstance(entry.value, dict)
    entry.value.clear()
    assert reader.read(first).value
    reader.read(second)
    assert reader.status()["entries"] == 1
    reader.read(first)
    assert transport.reused[-1] is False
    clock[0] = 2
    reader.read(first)
    assert transport.reused[-1] is False
    tiny = Reader(transport, lambda: None, Limits(entries=1, bytes=1))
    assert tiny.read(first).value and tiny.status()["entries"] == 0
