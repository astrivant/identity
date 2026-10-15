"""
Commit individually encrypted objects and complete multi-ref frontiers with PostgreSQL durability.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from importlib.resources import files
from typing import TYPE_CHECKING
from uuid import UUID

from attrs import field, frozen

from witful.exceptions import NativeError, StorageError
from witful.native import codec
from witful.native.storage import Batch, Head, Object, Scope
from witful.native.wire import decode_batch, encode_batch
from witful.storage.connection import connect

if TYPE_CHECKING:
    from collections.abc import Iterator

    import psycopg

__all__ = ["Postgres"]


def sql(name: str) -> str:
    """
    Load a package-owned SQL resource without accepting input-supplied paths.

    Args:
        name (str): Internal query filename.

    Returns:
        str: Versioned parameterized SQL.
    """
    return files("witful").joinpath("sql", "postgres", "native", name + ".sql").read_text()


def head_row(row: tuple[object, ...] | None) -> Head:
    """
    Validate untrusted storage types before constructing a frontier.

    Args:
        row (tuple[object, ...] | None): Driver values, or an uninitialized identity.

    Returns:
        Head: Validated opaque frontier; authenticity is checked against external authority.

    Raises:
        NativeError: Database values violate the storage contract.
    """
    if row is None:
        return Head()
    generation, root, digest = row
    if type(generation) is not int or not isinstance(digest, bytes) or (root is not None and not isinstance(root, UUID)):
        raise NativeError("invalid")
    return Head(generation, str(root) if root is not None else None, digest)


def binding(batch: Batch) -> bytes:
    """
    Bind an operation retry to every prepared ciphertext byte, including ordered outbox entries.

    Args:
        batch (Batch): Already sealed operation candidate.

    Returns:
        bytes: Ciphertext-only request digest, safe for the reviewed persistence leakage budget.
    """
    value = [
        batch.operation,
        batch.expected.generation,
        batch.expected.root,
        batch.expected.digest,
        [[item.id, item.digest] for item in (batch.root, batch.receipt, *batch.objects, *batch.outbox)],
    ]
    return hashlib.sha256(b"witful-native-transaction-v1\0" + codec.encode(value)).digest()


@frozen
class Postgres:
    """
    Persist only sealed records; a separate authority service controls admission and restore freshness.

    Attributes:
        database_url (str): Operator-owned TLS endpoint, never reflected in diagnostics.
        max_objects (int): Maximum objects in a read or transaction.
        max_bytes (int): Maximum aggregate ciphertext bytes per transaction or read.
        synchronous (bool): Require remote_apply and a configured synchronous standby policy.
    """

    database_url: str = field(repr=False)
    max_objects: int = 4096
    max_bytes: int = 64 * 1024 * 1024
    synchronous: bool = False

    def __attrs_post_init__(self) -> None:
        """
        Enforce finite resource budgets without arbitrary upper limits on operator configuration.

        Returns:
            None: Positive explicit budgets are configured.
        """
        if any(type(value) is not int or value < 1 for value in (self.max_objects, self.max_bytes)):
            raise NativeError("invalid")

    @contextmanager
    def transaction(self, scope: Scope) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
        """
        Require a least-privilege role and establish scoped RLS for one bounded durable transaction.

        Args:
            scope (Scope): Previously authorized tenant and identity.

        Yields:
            psycopg.Connection[tuple[object, ...]]: Scoped transaction with no plaintext record parameters.

        Raises:
            NativeError: The role, durability policy or database operation is unavailable.
        """
        try:
            with connect(self.database_url) as connection:
                if connection.execute(sql("role")).fetchone() != (False, False):
                    raise NativeError("denied")
                connection.execute(sql("scope"), (scope.tenant, scope.identity))
                required = "remote_apply" if self.synchronous else "on"
                connection.execute(sql("synchronous"), (required,))
                if connection.execute(sql("durability")).fetchone() != (required, "on"):
                    raise NativeError("denied")
                if self.synchronous:
                    row = connection.execute(sql("standbys")).fetchone()
                    if row is None or not row[0]:
                        raise NativeError("denied")
                yield connection
        except StorageError as error:
            if isinstance(error, NativeError):
                raise
            # A lost connection at commit cannot be classified as an uncommitted write.
            raise NativeError("unknown") from None

    def head(self, scope: Scope) -> Head:
        """
        Read a complete frontier without claiming that an external registry still authorizes it.

        Args:
            scope (Scope): Opaque partition selected by the trusted service.

        Returns:
            Head: Database snapshot frontier.
        """
        with self.transaction(scope) as connection:
            return head_row(connection.execute(sql("head"), (scope.tenant, scope.identity)).fetchone())

    def _get(self, connection: psycopg.Connection[tuple[object, ...]], scope: Scope, identifiers: tuple[str, ...]) -> tuple[Object, ...]:
        """
        Retrieve immutable ciphertext in caller order within an existing transaction.

        Args:
            connection (psycopg.Connection[tuple[object, ...]]): Scoped transaction.
            scope (Scope): Opaque partition.
            identifiers (tuple[str, ...]): Validated requested object IDs.

        Returns:
            tuple[Object, ...]: Complete bounded ciphertext result.

        Raises:
            NativeError: An object is missing, malformed or exceeds the aggregate budget.
        """
        if len(identifiers) > self.max_objects:
            raise NativeError("incomplete")
        rows = connection.execute(sql("get"), (scope.tenant, scope.identity, list(identifiers))).fetchall()
        objects: dict[str, Object] = {}
        size = 0
        for object_id, payload in rows:
            if not isinstance(object_id, UUID) or not isinstance(payload, bytes):
                raise NativeError("invalid")
            size += len(payload)
            if size > self.max_bytes:
                raise NativeError("incomplete")
            objects[str(object_id)] = Object(str(object_id), payload)
        if set(identifiers) != set(objects):
            raise NativeError("incomplete")
        return tuple(objects[value] for value in identifiers)

    def get(self, scope: Scope, identifiers: tuple[str, ...]) -> tuple[Object, ...]:
        """
        Read an exact bounded set without traversing unauthorized relationships.

        Args:
            scope (Scope): Admitted opaque scope.
            identifiers (tuple[str, ...]): Independently authorized IDs.

        Returns:
            tuple[Object, ...]: Ciphertext in the requested order.
        """
        with self.transaction(scope) as connection:
            return self._get(connection, scope, identifiers)

    def receipt(self, scope: Scope, operation: str) -> Object | None:
        """
        Retrieve a committed receipt before retrying an uncertain operation.

        Args:
            scope (Scope): Admitted opaque scope.
            operation (str): Stable operation ID.

        Returns:
            Object | None: Existing sealed receipt, or no observed commit.
        """
        with self.transaction(scope) as connection:
            row = connection.execute(sql("operation"), (scope.tenant, scope.identity, operation)).fetchone()
            if row is None:
                return None
            return self._get(connection, scope, (str(row[1]),))[0]

    def commit(self, scope: Scope, batch: Batch) -> Head:
        """
        Serialize one identity's complete frontier and commit its receipt and outbox with all objects.

        Args:
            scope (Scope): Scope already fenced by the independent authority service.
            batch (Batch): Exact prepared ciphertext, reused unchanged after unknown outcomes.

        Returns:
            Head: Durable target, including the original target on an exact duplicate retry.

        Raises:
            NativeError: A conflicting ID, changed operation, stale frontier, budget or storage failure blocks publication.
        """
        objects = (batch.root, batch.receipt, *batch.objects, *batch.outbox)
        if len(objects) > self.max_objects or sum(len(item.payload) for item in objects) > self.max_bytes:
            raise NativeError("incomplete")
        request_digest = binding(batch)
        with self.transaction(scope) as connection:
            # This row lock assigns the watermark in commit order, unlike a sequence allocation.
            connection.execute(sql("lock"), (scope.tenant, scope.identity))
            current = head_row(connection.execute(sql("locked-head"), (scope.tenant, scope.identity)).fetchone())
            previous = connection.execute(sql("operation"), (scope.tenant, scope.identity, batch.operation)).fetchone()
            if previous is not None:
                if previous[0] != request_digest:
                    raise NativeError("conflict")
                return head_row(previous[2:])
            if current != batch.expected:
                raise NativeError("conflict")
            for item in objects:
                connection.execute(sql("put"), (scope.tenant, scope.identity, item.id, item.payload))
            stored = self._get(connection, scope, tuple(item.id for item in objects))
            if stored != objects:
                raise NativeError("conflict")
            target = batch.target
            connection.execute(
                sql("commit"),
                (
                    scope.tenant,
                    scope.identity,
                    batch.operation,
                    request_digest,
                    batch.receipt.id,
                    target.generation,
                    target.root,
                    target.digest,
                    encode_batch(batch, codec.Limits(bytes=self.max_bytes, items=self.max_objects * 32)),
                ),
            )
            for item in batch.outbox:
                connection.execute(sql("outbox"), (scope.tenant, scope.identity, item.id, target.generation))
            connection.execute(sql("advance"), (target.generation, target.root, target.digest, scope.tenant, scope.identity))
        return target

    def history(self, scope: Scope) -> tuple[Batch, ...]:
        """
        Export the bounded complete committed transaction sequence for verified migration and restore.

        Args:
            scope (Scope): Independently authorized identity.

        Returns:
            tuple[Batch, ...]: Exact prepared ciphertext in commit order; never a plaintext compatibility dump.
        """
        with self.transaction(scope) as connection:
            rows = connection.execute(sql("history"), (scope.tenant, scope.identity, self.max_objects + 1)).fetchall()
            if len(rows) > self.max_objects:
                raise NativeError("incomplete")
            result: list[Batch] = []
            size = 0
            for row in rows:
                payload = row[0]
                if not isinstance(payload, bytes):
                    raise NativeError("invalid")
                size += len(payload)
                if size > self.max_bytes:
                    raise NativeError("incomplete")
                result.append(decode_batch(payload, codec.Limits(bytes=self.max_bytes, items=self.max_objects * 32)))
            return tuple(result)

    def resolve(self, scope: Scope, operation: str) -> tuple[Head, Object | None]:
        """
        Wait behind the data row lock before deciding whether an interrupted transaction committed.

        Args:
            scope (Scope): Current recovery scope.
            operation (str): Exact prepared operation UUID.

        Returns:
            tuple[Head, Object | None]: Settled frontier and receipt from one locked transaction.
        """
        with self.transaction(scope) as connection:
            connection.execute(sql("lock"), (scope.tenant, scope.identity))
            current = head_row(connection.execute(sql("locked-head"), (scope.tenant, scope.identity)).fetchone())
            row = connection.execute(sql("operation"), (scope.tenant, scope.identity, operation)).fetchone()
            receipt = self._get(connection, scope, (str(row[1]),))[0] if row is not None else None
            return current, receipt
