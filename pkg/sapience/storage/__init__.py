"""
Select a local disposable index or an append-only shared PostgreSQL lesson index.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

from sapience.lessons import rebuild_database, search
from sapience.storage.exceptions import StorageError

if TYPE_CHECKING:
    from pathlib import Path

    from sapience.lessons import Lesson

__all__ = ["LessonStore", "SQLiteStore", "StorageError", "open_store", "search_words", "validate_endpoint"]


class LessonStore(Protocol):
    """
    Index validated lessons without changing their versioned source journal.
    """

    def sync(self, records: list[Lesson]) -> None:
        """
        Make every supplied observation searchable atomically.

        Args:
            records (list[Lesson]): Complete validated source journal.

        Returns:
            None: SQLite replaces its index; PostgreSQL adds missing immutable observations.
        """
        ...

    def search(self, terms: str, *, history: bool = False, limit: int = 10) -> list[dict[str, object]]:
        """
        Retrieve matching lessons without interpreting text as executable query syntax.

        Args:
            terms (str): Literal words required in a result.
            history (bool): Include superseded records.
            limit (int): Maximum result count from one through one hundred.

        Returns:
            list[dict[str, object]]: Ranked records with superseded markers.
        """
        ...


@dataclass(frozen=True)
class SQLiteStore:
    """
    Adapt the existing local index without changing its format or permissions.

    Attributes:
        path (Path): Private local database destination.
    """

    path: Path

    def sync(self, records: list[Lesson]) -> None:
        """
        Atomically rebuild the local index from the current journal.

        Args:
            records (list[Lesson]): Validated source observations.

        Returns:
            None: The private database contains exactly the supplied history.
        """
        rebuild_database(self.path, records)

    def search(self, terms: str, *, history: bool = False, limit: int = 10) -> list[dict[str, object]]:
        """
        Search the SQLite full-text index.

        Args:
            terms (str): Literal required words.
            history (bool): Include superseded records.
            limit (int): Maximum number of matches.

        Returns:
            list[dict[str, object]]: Ranked matching observations.
        """
        return search(self.path, terms, history=history, limit=limit)


def search_words(terms: str, limit: int) -> list[str]:
    """
    Validate a literal full-text query independently of its SQL dialect.

    Args:
        terms (str): User-supplied search words.
        limit (int): Requested maximum result count.

    Returns:
        list[str]: Unicode word tokens, excluding query operators and punctuation.

    Raises:
        ValueError: There are no words or the limit is outside the supported range.
    """
    words = re.findall(r"\w+", terms, flags=re.UNICODE)

    if not words or not 1 <= limit <= 100:
        raise ValueError("Supply search words and a limit from 1 through 100")

    return words


def open_store(path: Path, *, database_url: str | None = None, namespace: str = "default") -> LessonStore:
    """
    Load the optional driver only when a PostgreSQL endpoint is explicitly selected.

    Args:
        path (Path): SQLite destination when no remote endpoint is configured.
        database_url (str | None): PostgreSQL URI, normally from SAPIENCE_DATABASE_URL.
        namespace (str): Stable identity partition shared by collaborating replicas.

    Returns:
        LessonStore: The chosen storage implementation; no connection is made yet.

    Raises:
        StorageError: The URI, namespace, or optional driver is unavailable or invalid.
    """
    if database_url is None:
        return SQLiteStore(path)

    validate_endpoint(database_url, namespace)

    try:
        from sapience.storage.postgres import PostgreSQLStore
    except ImportError:
        raise StorageError("PostgreSQL requires the optional driver: poetry install --extras postgres") from None

    return PostgreSQLStore(database_url, namespace)


def validate_endpoint(database_url: str, namespace: str) -> None:
    """
    Validate shared database settings without loading the optional PostgreSQL driver.

    Args:
        database_url (str): Secret PostgreSQL endpoint.
        namespace (str): Logical identity partition.

    Returns:
        None: Configuration can select the PostgreSQL backend.

    Raises:
        StorageError: Endpoint or namespace is invalid; supplied values are never echoed.
    """
    # A configured but invalid endpoint must never silently fall back to private local state.
    try:
        parsed = urlsplit(database_url)
    except ValueError:
        raise StorageError("SAPIENCE_DATABASE_URL must be a PostgreSQL URI") from None

    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise StorageError("SAPIENCE_DATABASE_URL must be a PostgreSQL URI with a host")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", namespace):
        raise StorageError("SAPIENCE_DATABASE_NAMESPACE must contain 1-128 letters, digits, dots, underscores, or hyphens")
