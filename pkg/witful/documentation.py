"""
Maintain explicit comment-to-document links without executing or interpreting repository instructions.
"""

from __future__ import annotations

import argparse
import hashlib
import posixpath
import re
import subprocess
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import quote

from attrs import frozen
from markdown_it import MarkdownIt
from pygments.lexers import get_all_lexers, get_lexer_by_name
from pygments.token import Comment, is_token_subtype

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

BEGIN = "<!-- docrefs:begin -->"
END = "<!-- docrefs:end -->"
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


def render(document: str, source: str, selected: Sequence[Reference]) -> str:
    """
    Replace only a managed reference block and verify actual Markdown links use each declaration.

    Args:
        document (str): Canonical Markdown path.
        source (str): Authored document, including any existing generated block.
        selected (Sequence[Reference]): Declarations explicitly naming this consumer.

    Returns:
        str: Updated Markdown with deterministic same-revision relative code links.

    Raises:
        ValueError: A managed block is ambiguous, unknown, unused, or declared inside an example.
    """
    parser = MarkdownIt()
    tokens = parser.parse(source)
    # HTML block tokens distinguish live markers from fenced or indented examples.
    boundaries = {
        marker: [token for token in tokens if token.type == "html_block" and token.content.strip() == marker] for marker in (BEGIN, END)
    }
    if any(len(items) > 1 for items in boundaries.values()) or bool(boundaries[BEGIN]) != bool(boundaries[END]):
        raise ValueError(f"Ambiguous docref block in {document}")
    if not selected and not boundaries[BEGIN]:
        return source
    links = {
        item.id: quote(posixpath.relpath(item.path, posixpath.dirname(document) or "."), safe="/.") + f"#L{item.line}" for item in selected
    }
    block = BEGIN + "\n\n" + "".join(f"[code:{key}]: {value}\n" for key, value in sorted(links.items())) + "\n" + END + "\n"
    lines = source.splitlines(keepends=True)
    if boundaries[BEGIN]:
        first, last = boundaries[BEGIN][0].map, boundaries[END][0].map
        if first is None or last is None or first[0] >= last[0]:
            raise ValueError(f"Invalid docref boundaries in {document}")
        body = "".join(lines[first[1] : last[0]])
        if any(line.strip() and not re.fullmatch(r"\[code:[a-z][a-z0-9_.-]*\]: \S+", line.strip()) for line in body.splitlines()):
            raise ValueError(f"Authored content inside docref block in {document}")
        previous = set(re.findall(r"\[code:([a-z][a-z0-9_.-]*)\]:", body))
        if previous - links.keys():
            raise ValueError(f"Removed source declaration still referenced by {document}")
        result = "".join(lines[: first[0]]) + block + "".join(lines[last[1] :])
    else:
        result = source.rstrip("\n") + "\n\n" + block
    # Probe reference usage with unique inert destinations so an unrelated inline URL cannot satisfy it.
    probe = result
    for key, value in links.items():
        probe = probe.replace(f"[code:{key}]: {value}\n", f"[code:{key}]: docref-check:{key}\n")
    parsed = parser.parse(probe)
    destinations = {child.attrGet("href") for token in parsed for child in token.children or () if child.type == "link_open"}
    if not {"docref-check:" + key for key in links} <= destinations:
        raise ValueError(f"Unused docref declaration in {document}; add an actual [Name][code:id] link")
    if any(
        child.type == "text" and re.search(r"\]\[code:[a-z][a-z0-9_.-]*\]", child.content)
        for token in parsed
        for child in token.children or ()
    ):
        raise ValueError(f"Unresolved docref link in {document}")
    return result


def updates(sources: Mapping[str, bytes]) -> dict[str, bytes]:
    """
    Plan every output before writing any document.

    Args:
        sources (Mapping[str, bytes]): Complete selected repository file snapshot.

    Returns:
        dict[str, bytes]: Changed documents only; inputs remain unchanged.

    Raises:
        ValueError: A consumer is missing or a managed block loses its source declaration.
    """
    found = discover(sources)
    consumers = {path for item in found for path in item.consumers}
    consumers.update(
        path for path, raw in sources.items() if PurePosixPath(path).suffix.lower() in {".md", ".markdown"} and BEGIN.encode() in raw
    )
    result: dict[str, bytes] = {}
    for path in sorted(consumers):
        if path not in sources:
            raise ValueError(f"Missing tracked Markdown consumer: {path}")
        old = sources[path]
        new = render(path, old.decode(), tuple(item for item in found if path in item.consumers)).encode()
        if old != new:
            result[path] = new
    return result


def declare(sources: Mapping[str, bytes], path: str, line: int, identifier: str, consumers: Sequence[str], prefix: str) -> dict[str, bytes]:
    """
    Insert one explicit source breadcrumb and plan its consumer links without guessing a definition.

    Args:
        sources (Mapping[str, bytes]): Complete selected repository snapshot.
        path (str): Explicit tracked source target.
        line (int): One-based declaration line selected by the maintainer.
        identifier (str): New stable ID, unique within this repository.
        consumers (Sequence[str]): Explicit local Markdown consumers already using the reference label.
        prefix (str): Native single-line comment prefix selected by the maintainer.

    Returns:
        dict[str, bytes]: Source and document changes, with no mutation of inputs.

    Raises:
        ValueError: The insertion is invalid, inside a string, ambiguous, or not a new declaration.
    """
    if path not in sources or prefix not in {"#", "//", "--", ";"} or not consumers:
        raise ValueError("Declaration requires a tracked source, comment prefix and consumers")
    if any(item.id == identifier for item in discover(sources)):
        raise ValueError("Declaration ID already exists; move the existing comment instead")
    lines = sources[path].decode().splitlines(keepends=True)
    if not 1 <= line <= len(lines) or not lines[line - 1].strip():
        raise ValueError("Declaration line is missing or blank")
    indentation = lines[line - 1][: len(lines[line - 1]) - len(lines[line - 1].lstrip())]
    marker = f"{indentation}{prefix} docref:1 {identifier} -> {' '.join(consumers)}\n"
    candidate = "".join((*lines[: line - 1], marker, *lines[line - 1 :])).encode()
    changed = {**sources, path: candidate}
    matches = [item for item in discover(changed) if item.id == identifier]
    if len(matches) != 1 or matches[0].path != path or matches[0].line != line + 1:
        raise ValueError("Insertion was not recognized as a standalone source comment")
    return {path: candidate, **updates(changed)}


def snapshot(root: Path, limit: int) -> dict[str, bytes]:
    """
    Read bounded tracked regular files without following symbolic links or Git metadata paths.

    Args:
        root (Path): Existing repository root.
        limit (int): Maximum aggregate bytes inspected.

    Returns:
        dict[str, bytes]: Local source bytes, including staged new files and current worktree edits.

    Raises:
        ValueError: Files escape the root, are missing, or exceed the byte budget.
    """
    output = subprocess.run(["git", "ls-files", "--cached", "-z"], cwd=root, check=True, capture_output=True).stdout
    result: dict[str, bytes] = {}
    remaining = limit
    for name in sorted(set(output.decode().split("\0")) - {""}):
        path = root / name
        if not local_path(name) or path.resolve() != path.absolute() or not path.is_file():
            raise ValueError("Tracked path is missing, symbolic, or not a regular file")
        with path.open("rb") as stream:
            raw = stream.read(remaining + 1)
        remaining -= len(raw)
        if remaining < 0:
            raise ValueError("Repository exceeds documentation byte budget")
        # Binary files cannot contain supported declarations; retain only UTF-8 text candidates.
        if b"\0" not in raw:
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            result[name] = raw
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """
    Check or explicitly update local source links; never stage files or make network requests.

    Args:
        argv (Sequence[str] | None): Arguments, or the process arguments when omitted.

    Returns:
        int: Zero for current or written outputs, one for drift, two for invalid inputs.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024)
    enrollment = parser.add_argument_group("explicit declaration enrollment")
    enrollment.add_argument("--declare", metavar="SOURCE")
    enrollment.add_argument("--line", type=int)
    enrollment.add_argument("--id", dest="identifier")
    enrollment.add_argument("--consumer", action="append", default=[])
    enrollment.add_argument("--comment-prefix", choices=("#", "//", "--", ";"))
    args = parser.parse_args(argv)
    if args.declare and (not args.write or not all((args.line, args.identifier, args.consumer, args.comment_prefix))):
        parser.error("--declare requires --write, --line, --id, --consumer and --comment-prefix")
    if not args.declare and any((args.line, args.identifier, args.consumer, args.comment_prefix)):
        parser.error("enrollment arguments require --declare")
    try:
        root = args.repo.resolve()
        if args.max_bytes < 1:
            raise ValueError("Byte budget must be positive")
        sources = snapshot(root, args.max_bytes)
        changed = (
            declare(sources, args.declare, args.line, args.identifier, args.consumer, args.comment_prefix)
            if args.declare
            else updates(sources)
        )
        if args.write:
            # Refuse concurrent edits before the first write; use the user's normal Git review afterward.
            if any((root / name).read_bytes() != sources[name] for name in sources):
                raise ValueError("Repository changed while preparing documentation links")
            for name, content in changed.items():
                (root / name).write_bytes(content)
        print(f"Source links: {len(changed)} file(s) {'updated' if args.write else 'need updating'}")
        return 0 if args.write or not changed else 1
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Source link validation failed: {error}")
        return 2
