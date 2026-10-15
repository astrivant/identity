"""
Provision disposable independent control/data databases and least-privilege roles for real PostgreSQL contracts.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from attrs import frozen
from psycopg import sql as query
from psycopg.conninfo import make_conninfo
from witful.native.postgres import sql

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
    Create isolated databases from the existing CI PostgreSQL service and remove only this fixture's objects.

    Yields:
        Databases: Separate roles and databases, using synthetic credentials only.
    """
    url = os.environ.get("WITFUL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("WITFUL_TEST_DATABASE_URL required for real native persistence contracts")
    suffix = uuid4().hex
    data, authority = "native_data_" + suffix, "native_authority_" + suffix
    roles = (data + "_role", authority + "_role")
    with psycopg.connect(url, autocommit=True) as admin:
        for name, role in zip((data, authority), roles, strict=True):
            admin.execute(query.SQL("CREATE ROLE {} LOGIN PASSWORD 'fixture'").format(query.Identifier(role)))
            admin.execute(query.SQL("CREATE DATABASE {}").format(query.Identifier(name)))
    data_admin, authority_admin = make_conninfo(url, dbname=data), make_conninfo(url, dbname=authority)
    try:
        with psycopg.connect(data_admin) as admin:
            admin.execute(sql("schema"))
            admin.execute(query.SQL("GRANT USAGE ON SCHEMA public TO {}").format(query.Identifier(roles[0])))
            admin.execute(query.SQL("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO {}").format(query.Identifier(roles[0])))
        with psycopg.connect(authority_admin) as admin:
            admin.execute(sql("authority-schema"))
            admin.execute(query.SQL("GRANT USAGE ON SCHEMA public TO {}").format(query.Identifier(roles[1])))
            admin.execute(query.SQL("GRANT SELECT, UPDATE ON witful_native_registry TO {}").format(query.Identifier(roles[1])))
            admin.execute(query.SQL("GRANT SELECT ON witful_native_grants TO {}").format(query.Identifier(roles[1])))
            admin.execute(
                query.SQL("GRANT EXECUTE ON FUNCTION witful_native_admit_grant(UUID, UUID, UUID, UUID) TO {}").format(
                    query.Identifier(roles[1])
                )
            )
        yield Databases(
            make_conninfo(data_admin, user=roles[0], password="fixture"),
            make_conninfo(authority_admin, user=roles[1], password="fixture"),
            data_admin,
            authority_admin,
        )
    finally:
        with psycopg.connect(url, autocommit=True) as admin:
            for name, role in zip((data, authority), roles, strict=True):
                admin.execute(query.SQL("DROP DATABASE {} WITH (FORCE)").format(query.Identifier(name)))
                admin.execute(query.SQL("DROP ROLE {}").format(query.Identifier(role)))
