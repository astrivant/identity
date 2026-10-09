"""
Keep sourced lessons append-only and materialize a private SQLite full-text index.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from witful.files import replace_file

_SQL = Path(__file__).parent / "sql" / "sqlite"


@dataclass(frozen=True)
class Lesson:
    """
    Retain one observed preference and its provenance without erasing earlier guidance.

    Attributes:
        id (str): Content-derived identifier independent of observation time.
        topic (str): Searchable responsibility or subject.
        lesson (str): User-taught rule, with its intended scope.
        source (str): Conversation reference, source commit, or user-supplied attribution.
        observed_at (str): Time of recording in timezone-aware ISO format; not an inferred date of origin.
        supersedes (str | None): Earlier lesson corrected by this record.
    """

    id: str
    topic: str
    lesson: str
    source: str
    observed_at: str
    supersedes: str | None = None


def new_lesson(topic: str, lesson: str, source: str, observed_at: str, supersedes: str | None = None) -> Lesson:
    """
    Give identical guidance and attribution the same identifier across machines.

    Args:
        topic (str): Subject label.
        lesson (str): Complete scoped guidance.
        source (str): Actual provenance, never invented attribution.
        observed_at (str): Explicit recording timestamp.
        supersedes (str | None): Earlier record identifier, if this is a correction.

    Returns:
        Lesson: Record ready for journal validation.
    """
    payload = json.dumps([topic, lesson, source, supersedes], ensure_ascii=False).encode()
    return Lesson(hashlib.sha256(payload).hexdigest(), topic, lesson, source, observed_at, supersedes)


def read_journal(path: Path) -> list[Lesson]:
    """
    Validate the complete export before mutating either the journal or its index.

    Args:
        path (Path): Reviewed JSONL export from the knowledge repository.

    Returns:
        list[Lesson]: Ordered records, including superseded history.

    Raises:
        ValueError: Invalid records, identifiers, timestamps, duplicate IDs, or unresolved correction references occur.
    """
    return parse_journal(path.read_text(encoding="utf-8"))


def parse_journal(text: str) -> list[Lesson]:
    """
    Validate saved lesson content without consulting current files or databases.

    Args:
        text (str): Complete JSONL lesson history.

    Returns:
        list[Lesson]: Validated records in source order, including superseded teachings.

    Raises:
        ValueError: The journal violates observation or supersession contracts.
    """
    records: list[Lesson] = []
    identifiers: set[str] = set()

    for number, line in enumerate(text.splitlines(), 1):
        value: object = json.loads(line)

        if not isinstance(value, dict) or set(value) != {"id", "topic", "lesson", "source", "observed_at", "supersedes"}:
            raise ValueError(f"Invalid lesson fields on line {number}")

        strings: dict[str, str] = {}

        for field in ("id", "topic", "lesson", "source", "observed_at"):
            item: object = value[field]

            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"Expected nonempty {field} on line {number}")

            strings[field] = item

        previous: object = value["supersedes"]

        if previous is not None and (not isinstance(previous, str) or previous not in identifiers):
            raise ValueError(f"Correction must reference an earlier record on line {number}")

        record = new_lesson(strings["topic"], strings["lesson"], strings["source"], strings["observed_at"], previous)

        if record.id != strings["id"] or record.id in identifiers:
            raise ValueError(f"Invalid or duplicate lesson ID on line {number}")

        if datetime.fromisoformat(record.observed_at).tzinfo is None:
            raise ValueError(f"Missing observation timezone on line {number}")

        records.append(record)
        identifiers.add(record.id)

    return records


def append_lesson(path: Path, record: Lesson) -> Lesson:
    """
    Append a validated observation without changing any existing record.

    Args:
        path (Path): Existing export, protected by the caller's exclusive file lock.
        record (Lesson): New rule or explicit correction.

    Returns:
        Lesson: The existing record for a duplicate observation, otherwise the newly appended record.

    Raises:
        ValueError: The correction target is not present or the timestamp is invalid.
    """
    original = path.read_bytes()
    records = read_journal(path)

    for previous in records:
        if previous.id == record.id:
            return previous

    if record.supersedes is not None and record.supersedes not in {item.id for item in records}:
        raise ValueError("A correction must reference an existing lesson")

    if datetime.fromisoformat(record.observed_at).tzinfo is None:
        raise ValueError("Observation time must include a timezone")

    if not all(value.strip() for value in (record.topic, record.lesson, record.source)):
        raise ValueError("Topic, lesson, and source must not be blank")

    separator = b"\n" if original and not original.endswith(b"\n") else b""
    encoded = json.dumps(asdict(record), ensure_ascii=False, sort_keys=True).encode() + b"\n"
    replace_file(path, original + separator + encoded, expected=original)
    return record


def rebuild_database(path: Path, records: list[Lesson]) -> None:
    """
    Rebuild a disposable index atomically, checking SQL syntax with SQLite itself.

    Args:
        path (Path): Local SQLite destination; never committed to Git.
        records (list[Lesson]): Validated history from the versioned export.

    Returns:
        None: A complete mode-0600 database replaces the previous index after successful validation.

    Raises:
        sqlite3.Error: SQLite lacks FTS5 support or rejects the schema, query, or records.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".lessons-")
    os.close(descriptor)
    staging = Path(temporary)

    try:
        with closing(sqlite3.connect(staging)) as connection, connection:
            connection.executescript((_SQL / "schema.sql").read_text())
            connection.executemany((_SQL / "insert.sql").read_text(), [asdict(record) for record in records])

            connection.execute((_SQL / "populate.sql").read_text())

            # Preparing and running the public query validates all separately maintained SQL resources.
            connection.execute((_SQL / "search.sql").read_text(), {"query": '"validation"', "history": True, "limit": 1}).fetchall()

        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)


def search(path: Path, terms: str, *, history: bool = False, limit: int = 10) -> list[dict[str, object]]:
    """
    Search literal words without interpreting user text as SQL or FTS operators.

    Args:
        path (Path): Prepared SQLite index.
        terms (str): Words that must all appear in a record.
        history (bool): Include superseded lessons when True.
        limit (int): Maximum matches, from 1 through 100.

    Returns:
        list[dict[str, object]]: Ranked records with an explicit superseded marker.

    Raises:
        ValueError: Search words are absent or the result limit is unsupported.
    """
    tokens = re.findall(r"\w+", terms, flags=re.UNICODE)

    if not tokens or not 1 <= limit <= 100:
        raise ValueError("Supply search words and a limit from 1 through 100")

    query = " AND ".join(f'"{token}"' for token in tokens)

    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        cursor = connection.execute((_SQL / "search.sql").read_text(), {"query": query, "history": history, "limit": limit})
        return [dict(row) for row in cursor.fetchall()]
