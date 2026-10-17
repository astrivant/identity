"""
Parse source declarations for admitted intent evidence without editing repositories.
"""

from __future__ import annotations

import hashlib
import re
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from attrs import frozen
from pygments.lexers import get_all_lexers, get_lexer_by_name
from pygments.token import Comment, is_token_subtype

if TYPE_CHECKING:
    from collections.abc import Mapping

MARKER = re.compile(r"(?:#|//|--|;) docref:1 ([a-z][a-z0-9_.-]*) -> (\S+(?: \S+)*)\r?\n?\Z")


@frozen
class Reference:
    """
    Bind a stable declaration to exact source bytes and explicitly named consumers.

    Attributes:
        id (str): Repository-local stable declaration identifier.
        path (str): POSIX source path relative to the repository.
        digest (str): SHA-256 of the complete source file.
        start (int): Inclusive byte offset of the comment.
        end (int): Exclusive byte offset of the comment.
        line (int): One-based declaration line following the comment.
        consumers (tuple[str, ...]): Explicit local Markdown consumers.
        text (str): Exact comment bytes decoded as UTF-8, including its newline if present.
    """

    id: str
    path: str
    digest: str
    start: int
    end: int
    line: int
    consumers: tuple[str, ...]
    text: str


def local_path(value: str) -> bool:
    """
    Accept only canonical repository-relative paths, with no traversal or control characters.

    Args:
        value (str): Untrusted path from a source declaration or Git inventory.

    Returns:
        bool: Whether the path can identify a local managed file.
    """
    path = PurePosixPath(value)
    return (
        bool(value)
        and not path.is_absolute()
        and path.as_posix() == value
        and not any(part in {"..", ".git"} for part in path.parts)
        and not any(ord(character) < 32 or character in "\\:#?" for character in value)
    )


def references(path: str, raw: bytes) -> tuple[Reference, ...]:
    """
    Read declarations only from standalone single-line comments recognized by a builtin lexer.

    Args:
        path (str): Canonical repository-relative source filename.
        raw (bytes): Complete unchanged UTF-8 source, never imported or executed.

    Returns:
        tuple[Reference, ...]: Exact comment declarations; strings and documentation examples are inert.

    Raises:
        ValueError: A marked source has no supported lexer or contains an invalid declaration.
    """
    if b"docref:" not in raw or PurePosixPath(path).suffix.lower() in {".md", ".markdown"}:
        return ()
    if not local_path(path):
        raise ValueError("Noncanonical source path")
    source = raw.decode("utf-8")
    # Choose only installed builtin lexers; repository code and third-party lexer plugins are never loaded.
    candidates = [
        get_lexer_by_name(aliases[0])
        for _, aliases, patterns, _ in get_all_lexers(plugins=False)
        if aliases and any(fnmatchcase(PurePosixPath(path).name, pattern) for pattern in patterns)
    ]
    if not candidates:
        raise ValueError(f"No builtin comment lexer for {path}")
    lexer = max(candidates, key=lambda item: (item.analyse_text(source), item.priority, item.name))
    result: list[Reference] = []
    for offset, kind, value in lexer.get_tokens_unprocessed(source):
        if not is_token_subtype(kind, Comment) or "docref:" not in value:
            continue
        match = MARKER.fullmatch(value)
        prefix = source[source.rfind("\n", 0, offset) + 1 : offset]
        if match is None or prefix.strip():
            raise ValueError(f"Malformed standalone docref comment in {path}")
        consumers = tuple(match[2].split())
        if len(set(consumers)) != len(consumers) or any(
            not local_path(item) or PurePosixPath(item).suffix.lower() not in {".md", ".markdown"} for item in consumers
        ):
            raise ValueError(f"Invalid docref consumer in {path}")
        # Require adjacent code. Blank lines/comments must not silently shift an anchor to another definition.
        following = source[offset + len(value) :]
        if not value.endswith("\n"):
            following = following.removeprefix("\r\n").removeprefix("\n")
        first = following.splitlines()[0] if following else ""
        if not first.strip() or first.lstrip().startswith(("#", "//", "--", ";")):
            raise ValueError(f"docref requires a following declaration in {path}")
        line = source[:offset].count("\n") + 2
        result.append(
            Reference(
                match[1],
                path,
                hashlib.sha256(raw).hexdigest(),
                len(source[:offset].encode()),
                len(source[: offset + len(value)].encode()),
                line,
                consumers,
                value,
            )
        )
    return tuple(result)


def discover(sources: Mapping[str, bytes]) -> tuple[Reference, ...]:
    """
    Collect unique declarations while preserving explicit consumer ownership.

    Args:
        sources (Mapping[str, bytes]): Selected source files and their exact bytes.

    Returns:
        tuple[Reference, ...]: Stable ID order independent of input iteration.

    Raises:
        ValueError: Two declarations claim the same ID.
    """
    found = [item for path, raw in sorted(sources.items()) for item in references(path, raw)]
    if len({item.id for item in found}) != len(found):
        raise ValueError("Duplicate docref ID; moves must preserve a single declaration")
    return tuple(sorted(found, key=lambda item: item.id))
