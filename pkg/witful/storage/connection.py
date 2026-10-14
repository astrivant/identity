"""
Share bounded, credential-safe PostgreSQL transactions between application stores.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import tuple_row

from witful.exceptions import StorageError

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["connect"]


@contextmanager
def connect(database_url: str) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """
    Bound connection, lock, and query waits while suppressing driver credential details.

    Args:
        database_url (str): Secret PostgreSQL connection URI.

    Yields:
        psycopg.Connection[tuple[object, ...]]: Transaction rolled back on failure and closed on exit.

    Raises:
        StorageError: Connection or SQL failure, identified by safe SQLSTATE when available.
    """
    try:
        options = conninfo_to_dict(database_url)

        # Explicit URL sslmode is respected for local development; remote defaults verify certificates and hostnames.
        connection: psycopg.Connection[tuple[object, ...]] = psycopg.connect(
            database_url,
            row_factory=tuple_row,
            connect_timeout=10,
            sslmode=options.get("sslmode", "verify-full"),
            options="-c statement_timeout=30000 -c lock_timeout=10000",
            application_name="witful",
        )
        with connection:
            yield connection
    except psycopg.Error as error:
        code = error.sqlstate or "connection"
        raise StorageError(f"PostgreSQL operation failed ({code}); check endpoint access, TLS, and database permissions") from None
