"""
Fence storage operations with an independently administered, durable PostgreSQL authority and maintained policy evaluator.
"""

from __future__ import annotations

from contextlib import contextmanager
from importlib.resources import as_file, files
from typing import TYPE_CHECKING, Protocol

from attrs import field, frozen
from casbin import Enforcer

from witful.exceptions import NativeError, StorageError
from witful.native import codec
from witful.native.context import identifier
from witful.native.postgres import head_row, sql
from witful.native.wire import binary, decode_batch, encode_batch, integer, text
from witful.storage.connection import connect

if TYPE_CHECKING:
    from collections.abc import Iterator

    import psycopg

    from witful.native.storage import Batch, Head, Scope, Store

__all__ = ["Access", "Authority", "Grant", "Registration"]


@frozen
class Access:
    """
    Bind a request to its authenticated transport identity and explicit current authority expectations.

    Attributes:
        scope (Scope): Tenant and identity routing.
        subject (str): SHA-256 of the TLS-authenticated peer certificate, never a request header.
        grant (str): Independently provisioned grant UUID.
        task (str): Explicit task UUID.
        epoch (int): Expected monotonic backend epoch.
        policy (str): Expected policy revision UUID.
    """

    scope: Scope
    subject: str
    grant: str
    task: str
    epoch: int
    policy: str

    def __attrs_post_init__(self) -> None:
        """
        Reject malformed bindings before opening a database connection.

        Returns:
            None: Bindings are structurally valid, not yet authorized.
        """
        for value in (self.grant, self.task, self.policy):
            identifier(value)
        if type(self.epoch) is not int or self.epoch < 1 or len(self.subject) != 64:
            raise NativeError("invalid")
        if any(value not in "0123456789abcdef" for value in self.subject):
            raise NativeError("invalid")


@frozen
class Grant:
    """
    Supply explicit opaque policy attributes to PyCasbin, with no application-owned authorization algorithm.

    Attributes:
        subject (str): Authorized certificate fingerprint.
        task (str): Authorized task UUID.
        actions (tuple[str, ...]): Enumerated permitted native operations.
        records (tuple[str, ...]): Exact logical UUIDs or the explicit whole-identity wildcard.
        starts (int): UTC validity start in epoch seconds.
        expires (int): Exclusive UTC expiration in epoch seconds.
    """

    subject: str
    task: str
    actions: tuple[str, ...]
    records: tuple[str, ...]
    starts: int
    expires: int


@frozen
class Registration:
    """
    Select one trusted backend and expected frontier independently of that backend's own metadata.

    Attributes:
        backend (str): Operator-assigned backend UUID.
        epoch (int): Monotonic fencing generation.
        policy (str): Current policy revision UUID.
        head (Head): Last acknowledged durable frontier.
        pending (bytes | None): Exact ciphertext-only prepared transaction requiring reconciliation.
    """

    backend: str
    epoch: int
    policy: str
    head: Head
    pending: bytes | None = field(repr=False)


class Evaluator(Protocol):
    """
    Contain the maintained evaluator's variadic boundary behind its actual public contract.
    """

    def enforce(self, *rvals: object) -> bool:
        """
        Evaluate the packaged attribute policy.

        Args:
            *rvals (object): Ordered attributes matching the request definition.

        Returns:
            bool: Maintained evaluator's decision.
        """
        ...


@frozen
class Authority:
    """
    Coordinate a durable prepare, fenced apply and recoverable acknowledgment across independent stores.

    Attributes:
        database_url (str): Separately administered control database, never the ciphertext data-role credential.
        backend (str): Configured storage instance UUID; config alone cannot change the registered authority.
        limits (codec.Limits): Aggregate prepared-transaction budget.
    """

    database_url: str = field(repr=False)
    backend: str
    limits: codec.Limits = codec.Limits(bytes=64 * 1024 * 1024, items=200_000)

    @contextmanager
    def guard(
        self, access: Access, action: str, record: str, now: int
    ) -> Iterator[tuple[psycopg.Connection[tuple[object, ...]], Registration]]:
        """
        Serialize current authorization and backend fencing; never call the key service inside this boundary.

        Args:
            access (Access): Authenticated request bindings.
            action (str): Native policy action.
            record (str): Exact logical UUID or explicit whole-identity request.
            now (int): Fresh trusted clock observation at this admission or release boundary.

        Yields:
            tuple[psycopg.Connection[tuple[object, ...]], Registration]: Locked control transaction and current registry state.
        """
        try:
            with connect(self.database_url) as connection:
                if connection.execute(sql("role")).fetchone() != (False, False):
                    raise NativeError("denied")
                row = connection.execute(sql("authority-lock"), (access.scope.tenant, access.scope.identity)).fetchone()
                if row is None or len(row) != 7:
                    raise NativeError("denied")
                registration = Registration(
                    str(row[0]), integer(row[1]), str(row[2]), head_row(row[3:6]), None if row[6] is None else binary(row[6])
                )
                if registration.backend != self.backend or registration.epoch != access.epoch or registration.policy != access.policy:
                    raise NativeError("conflict")
                grant_row = connection.execute(
                    sql("authority-grant"), (access.scope.tenant, access.scope.identity, access.policy, access.grant)
                ).fetchone()
                if grant_row is None:
                    raise NativeError("denied")
                subject, task, actions, records, starts, expires = grant_row
                if not isinstance(actions, list) or not isinstance(records, list):
                    raise NativeError("invalid")
                grant = Grant(
                    text(subject),
                    str(task),
                    tuple(text(item) for item in actions),
                    tuple(text(item) for item in records),
                    integer(starts),
                    integer(expires),
                )
                with as_file(files("witful.native").joinpath("resources", "authorization.conf")) as model:
                    evaluator: Evaluator = Enforcer(str(model), enable_log=False)
                if evaluator.enforce(grant, access.subject, access.task, action, record, now) is not True:
                    raise NativeError("denied")
                yield connection, registration
        except StorageError as error:
            if isinstance(error, NativeError):
                raise
            raise NativeError("unknown") from None

    def check(self, access: Access, action: str, record: str, now: int) -> Registration:
        """
        Reauthorize each read and result release rather than treating cache TTL as a grant.

        Args:
            access (Access): Authenticated request.
            action (str): Requested policy operation.
            record (str): Exact target or whole-identity scope.
            now (int): Current trusted time.

        Returns:
            Registration: Admitted committed frontier; unresolved prepares block ordinary operations.
        """
        with self.guard(access, action, record, now) as (_, registration):
            if registration.pending is not None:
                raise NativeError("unknown")
            return registration

    def prepare(self, access: Access, batch: Batch, now: int) -> None:
        """
        Durably retain exact sealed bytes before the data store can observe any mutation.

        Args:
            access (Access): Current whole-identity writer grant.
            batch (Batch): Complete candidate sealed outside all database locks.
            now (int): Current admission time.

        Returns:
            None: Candidate is durable; no data-store mutation is implied.
        """
        payload = encode_batch(batch, self.limits)
        with self.guard(access, "write", "*", now) as (connection, registration):
            if registration.head != batch.expected:
                raise NativeError("conflict")
            if registration.pending is not None and registration.pending != payload:
                raise NativeError("unknown")
            connection.execute(sql("authority-prepare"), (payload, access.scope.tenant, access.scope.identity))

    def apply(self, access: Access, store: Store, now: int) -> Head:
        """
        Fence the data transaction and acknowledge only its exact prepared result.

        Args:
            access (Access): Still-current whole-identity writer grant.
            store (Store): Registered ciphertext-only store.
            now (int): Fresh admission time after key operations have finished.

        Returns:
            Head: Durably acknowledged frontier; a lost acknowledgment leaves the earlier prepare recoverable.
        """
        with self.guard(access, "write", "*", now) as (connection, registration):
            if registration.pending is None:
                raise NativeError("conflict")
            batch = decode_batch(registration.pending, self.limits)
            if batch.expected != registration.head:
                raise NativeError("conflict")
            target = store.commit(access.scope, batch)
            if target != batch.target:
                raise NativeError("invalid")
            connection.execute(
                sql("authority-ack"), (target.generation, target.root, target.digest, access.scope.tenant, access.scope.identity)
            )
        return target

    def recover(self, access: Access, store: Store, now: int) -> Head:
        """
        Reconcile an uncertain effect by exact independent readback, without repeating a revoked write.

        Args:
            access (Access): Current recovery grant; old policies do not regain permission.
            store (Store): Currently registered data store.
            now (int): Fresh trusted time.

        Returns:
            Head: Acknowledged committed target or unchanged frontier after proving no commit occurred.
        """
        with self.guard(access, "recover", "*", now) as (connection, registration):
            current = store.head(access.scope)
            if registration.pending is None:
                if current != registration.head:
                    raise NativeError("conflict")
                return current
            batch = decode_batch(registration.pending, self.limits)
            receipt = store.receipt(access.scope, batch.operation)
            if receipt == batch.receipt and current == batch.target:
                target = batch.target
            elif receipt is None and current == batch.expected:
                target = batch.expected
            else:
                raise NativeError("conflict")
            connection.execute(
                sql("authority-ack"), (target.generation, target.root, target.digest, access.scope.tenant, access.scope.identity)
            )
        return target
