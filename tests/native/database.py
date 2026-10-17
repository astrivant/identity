"""
Provision disposable independent control/data databases and least-privilege roles for real PostgreSQL contracts.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from attrs import frozen
from psycopg import sql as query
from psycopg.conninfo import make_conninfo
from witful.native.administration import provision

if TYPE_CHECKING:
    from collections.abc import Iterator


@frozen
class Databases:
    """
    Retain synthetic service URLs independently of production configuration.

    Attributes:
        data (str): Least-privilege ciphertext connection.
        authority (str): Separate control-plane connection.
        data_admin (str): Test fixture administration only.
        authority_admin (str): Test fixture administration only.
    """

    data: str
    authority: str
    data_admin: str
    authority_admin: str


@pytest.fixture(scope="session")
def databases() -> Iterator[Databases]:
    """
    Provision test-only databases on an explicitly selected PostgreSQL service.

    Yields:
        Databases: Separate least-privilege data and authority connections.
    """
    url = os.environ.get("WITFUL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("WITFUL_TEST_DATABASE_URL required for real native persistence contracts")
    with isolated(url) as result:
        yield result


@contextmanager
def isolated(url: str, cleanup: bool = True) -> Iterator[Databases]:
    """
    Create and remove uniquely named synthetic databases and roles through the reviewed operator plans.

    Args:
        url (str): Explicit disposable administrator connection, never a production default.
        cleanup (bool): Remove databases/roles on exit; false only when an owning drill destroys the complete container volumes.

    Yields:
        Databases: Separate roles and databases; teardown removes only this invocation's synthetic resources.
    """
    suffix = uuid4().hex
    data, authority = "native_data_" + suffix, "native_authority_" + suffix
    roles = (data + "_role", authority + "_role")
    with psycopg.connect(url, autocommit=True) as admin:
        for name, role in zip((data, authority), roles, strict=True):
            admin.execute(query.SQL("CREATE ROLE {} LOGIN PASSWORD 'fixture'").format(query.Identifier(role)))
            admin.execute(query.SQL("CREATE DATABASE {}").format(query.Identifier(name)))
    data_admin = make_conninfo(url, dbname=data, application_name="witful-native-contract")
    authority_admin = make_conninfo(url, dbname=authority, application_name="witful-native-contract")
    try:
        # Complete operator plans own BEGIN/COMMIT; prevent the driver from issuing a second BEGIN.
        with psycopg.connect(data_admin, autocommit=True) as admin:
            admin.execute(provision("data", roles[0]))
        with psycopg.connect(authority_admin, autocommit=True) as admin:
            admin.execute(provision("authority", roles[1]))
        yield Databases(
            make_conninfo(data_admin, user=roles[0], password="fixture"),
            make_conninfo(authority_admin, user=roles[1], password="fixture"),
            data_admin,
            authority_admin,
        )
    finally:
        if cleanup:
            with psycopg.connect(url, autocommit=True) as admin:
                for name, role in zip((data, authority), roles, strict=True):
                    admin.execute(query.SQL("DROP DATABASE {} WITH (FORCE)").format(query.Identifier(name)))
                    admin.execute(query.SQL("DROP ROLE {}").format(query.Identifier(role)))
