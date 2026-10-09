"""
Merge reviewed lesson journals into a shared, namespaced PostgreSQL search index.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from witful.storage import search_words
from witful.storage.connection import connect

if TYPE_CHECKING:
    from witful.lessons import Lesson

__all__ = ["PostgreSQLStore"]

_SQL = Path(__file__).parents[1] / "sql" / "postgres"
_FIELDS = ("id", "topic", "lesson", "source", "observed_at", "supersedes", "superseded")


@dataclass(frozen=True)
class PostgreSQLStore:
    """
    Share immutable observations across replicas without deleting another checkout's data.

    Attributes:
        database_url (str): Secret endpoint, excluded from repr and error messages.
        namespace (str): Logical identity partition, not an authorization boundary.
    """

    database_url: str = field(repr=False)
    namespace: str = "default"

    def sync(self, records: list[Lesson]) -> None:
        """
        Insert a reviewed journal atomically, retaining previously shared history.

        Args:
            records (list[Lesson]): Validated records, including any referenced predecessors.

        Returns:
            None: All observations are searchable; duplicate IDs preserve their original timestamps.

        Raises:
            StorageError: The schema or journal cannot be committed; no partial sync is retained.
        """
        with connect(self.database_url) as connection:
            # Serialize initial DDL and journal writes across processes, including competing first starts.
            connection.execute((_SQL / "lock.sql").read_text())
            connection.execute((_SQL / "schema.sql").read_text())

            with connection.cursor() as cursor:
                cursor.executemany(
                    (_SQL / "insert.sql").read_text(),
                    [{**asdict(record), "namespace": self.namespace} for record in records],
                )

    def search(self, terms: str, *, history: bool = False, limit: int = 10) -> list[dict[str, object]]:
        """
        Search current shared lessons, including observations published by other replicas.

        Args:
            terms (str): Literal words combined by PostgreSQL's simple full-text parser.
            history (bool): Include superseded records.
            limit (int): Maximum number of matches from one through one hundred.

        Returns:
            list[dict[str, object]]: Deterministically ranked records with boolean superseded markers.
        """
        words = search_words(terms, limit)

        with connect(self.database_url) as connection:
            rows = connection.execute(
                (_SQL / "search.sql").read_text(),
                {"namespace": self.namespace, "query": " ".join(words), "history": history, "limit": limit},
            ).fetchall()
            return [dict(zip(_FIELDS, row, strict=True)) for row in rows]
