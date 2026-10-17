"""
Render reviewable PostgreSQL provisioning plans without connecting as an administrator or granting runtime administration.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import TYPE_CHECKING, Literal

from attrs import frozen
from psycopg import sql as query

from witful.collection.protection import require_protected
from witful.exceptions import NativeError, StorageProtectionError
from witful.knowledge.contracts import schema
from witful.native.authority import Access  # noqa: TC001 - closed enrollment schema resolves nested bindings at runtime.
from witful.native.context import identifier
from witful.native.models import parse
from witful.native.postgres import sql

if TYPE_CHECKING:
    import argparse


@frozen
class Enrollment:
    """
    Request one new independently reviewed identity registration and certificate/task-scoped grant.

    Attributes:
        access (Access): Exact tenant, identity, fingerprint, grant, task, initial epoch and policy.
        backend (str): Approved initial backend UUID.
        actions (tuple[str, ...]): Explicit native actions, with no implicit administrative or custody capability.
        records (tuple[str, ...]): Exact revision UUIDs or the explicitly reviewed whole-identity wildcard.
        starts (int): UTC epoch seconds at which this grant becomes usable.
        expires (int): Exclusive UTC expiry, strictly after starts.
    """

    access: Access
    backend: str
    actions: tuple[str, ...]
    records: tuple[str, ...]
    starts: int
    expires: int

    def __attrs_post_init__(self) -> None:
        """
        Refuse ambiguous enrollment, existing-epoch adoption and unknown capabilities before emitting SQL.

        Returns:
            None: The request is structurally valid; an independent administrator still reviews and applies it.
        """
        identifier(self.backend)
        allowed = {
            "read",
            "traverse",
            "search",
            "write",
            "review",
            "derive",
            "import",
            "export",
            "recover",
            "migrate",
            "rotate",
            "project",
            "codegraph-build",
            "codegraph-query",
            "intent-write",
            "intent-query",
            "intent-review",
        }
        if (
            self.access.epoch != 1
            or not self.actions
            or len(set(self.actions)) != len(self.actions)
            or not set(self.actions) <= allowed
            or not self.records
            or len(set(self.records)) != len(self.records)
            or ("*" in self.records and self.records != ("*",))
            or self.starts < 0
            or self.expires <= self.starts
        ):
            raise NativeError("invalid")
        for record in self.records:
            if record != "*":
                identifier(record)


def provision(kind: Literal["data", "authority"], role: str) -> str:
    """
    Emit an atomic schema and least-privilege role plan for an existing dedicated database and login.

    Args:
        kind (Literal["data", "authority"]): Independently administered database responsibility.
        role (str): Existing unprivileged login; creation and credential delivery remain the database operator's responsibility.

    Returns:
        str: Complete BEGIN/COMMIT plan for psql or an idle autocommit connection; rejects privileged runtime roles.
    """
    if kind not in {"data", "authority"} or re.fullmatch(r"[a-z][a-z0-9_]{0,62}", role) is None:
        raise NativeError("invalid")
    # Slots are trusted packaged SQL; identifiers and literals are quoted by psycopg rather than shell or text interpolation.
    bindings = {"role": query.Identifier(role).as_string(), "name": query.Literal(role).as_string()}
    guard = sql("administration/role") % bindings
    definition = sql("schema" if kind == "data" else "authority-schema")
    grants = sql(f"administration/{kind}") % bindings
    return "BEGIN;\n" + guard + definition + grants + "COMMIT;\n"


def enrollment(value: Enrollment) -> str:
    """
    Render new-scope enrollment without overwriting existing grants, policy, routes or retained history.

    Args:
        value (Enrollment): Explicit reviewed initial identity and permission contract.

    Returns:
        str: Complete BEGIN/COMMIT plan for psql or an idle autocommit connection; duplicate enrollment fails visibly.
    """
    access = value.access
    bindings = {
        key: query.Literal(item).as_string()
        for key, item in {
            "tenant": access.scope.tenant,
            "identity": access.scope.identity,
            "backend": value.backend,
            "policy": access.policy,
            "grant": access.grant,
            "subject": access.subject,
            "task": access.task,
            "actions": list(value.actions),
            "records": list(value.records),
            "starts": value.starts,
            "expires": value.expires,
        }.items()
    }
    return "BEGIN;\n" + sql("administration/enroll") % bindings + "COMMIT;\n"


def execute(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """
    Write an exclusive private SQL plan or emit its schema without opening any network or database connection.

    Args:
        args (argparse.Namespace): Recursively parsed administration leaf.
        parser (argparse.ArgumentParser): Owning parser, retained for the common dispatch contract.

    Returns:
        int: Zero on a complete plan, one on a redacted validation or filesystem failure.
    """
    try:
        if args.native_administration == "contract":
            print(json.dumps(schema(Enrollment), indent=2))
            return 0
        require_protected(args.output.parent)
        if args.native_administration == "enroll":
            require_protected(args.input)
            with args.input.open("rb") as source:
                raw = source.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise NativeError("incomplete")
            result = enrollment(parse(json.loads(raw), Enrollment))
        else:
            result = provision(args.kind, args.role)
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
            destination.write(result)
            destination.flush()
            os.fsync(destination.fileno())
        print("Reviewable SQL plan written; no database changes applied")
        return 0
    except (NativeError, StorageProtectionError, OSError, ValueError):
        print("Native administration plan failed", file=sys.stderr)
        return 1
