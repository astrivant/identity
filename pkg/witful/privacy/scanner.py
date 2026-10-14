"""
Detect explicit personal-data patterns without echoing matched values.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
from typing import TYPE_CHECKING

from attrs import frozen
from jsonschema import ValidationError

from witful.collection.models import CONFIG, MAX_BYTES, Envelope, file_path, parse_config
from witful.knowledge.contracts import structure

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

__all__ = ["Finding", "scan", "scan_text"]

_RULES = {
    "email": re.compile(r"\b[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[A-Z0-9-]+\.)+[A-Z]{2,}\b", re.I),
    "personal-home": re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+|[A-Z]:\\Users\\[A-Za-z0-9_.-]+"),
    "phone": re.compile(r"(?<![\w.])(?:\+\d{1,3}[ .-])?(?:\(\d{3}\)|\d{3})[ .-]\d{3}[ .-]\d{4}(?![\w.])"),
    "government-id": re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),
    "profile-url": re.compile(r"https?://(?:[a-z]+\.)?linkedin\.com/in/[^\s/\"<>]+", re.I),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
}
_SAFE_HOMES = {"/home/runner", "/home/witful"}
_SYNTHETIC_EMAIL_DOMAINS = {"example.com", "example.org", "example.net"}
_ENVELOPES = {"collection/sources.enc.json", "collection/figures.enc.json"}


@frozen
class Finding:
    """
    Locate a finding without retaining the sensitive match or its surrounding text.

    Attributes:
        path (str): Relative path, replaced by a digest label if its name is itself sensitive.
        line (int): One-based line number, or zero for file-level failures.
        rule (str): Detector identifier, never its matched value.
    """

    path: str
    line: int
    rule: str


def scan_text(text: str, terms: Sequence[str] = ()) -> tuple[tuple[int, str], ...]:
    """
    Report known patterns and case-insensitive literal deny terms in arbitrary text.

    Args:
        text (str): Decoded source, filenames, or a synthetic test fixture.
        terms (Sequence[str]): Private user-supplied literals; never returned in diagnostics.

    Returns:
        tuple[tuple[int, str], ...]: Stable unique line/rule pairs, without matched data.
    """
    found: set[tuple[int, str]] = set()

    for rule, pattern in _RULES.items():
        for match in pattern.finditer(text):
            value = match.group()

            if rule == "personal-home" and value in _SAFE_HOMES:
                continue
            if rule == "email":
                # GitHub uses this shared SSH principal; it is not a personal email address.
                if value == "git@github.com":
                    continue

                domain = value.rsplit("@", 1)[-1].lower()

                if domain in _SYNTHETIC_EMAIL_DOMAINS or domain.endswith((".invalid", ".test")):
                    continue
                if domain == "users.noreply.github.com" and value.endswith("[bot]@" + domain):
                    continue

            found.add((text.count("\n", 0, match.start()) + 1, rule))

    for term in terms:
        if term.strip():
            for match in re.finditer(re.escape(term), text, re.I):
                found.add((text.count("\n", 0, match.start()) + 1, "deny-term"))

    return tuple(sorted(found))


def _git(root: Path, *arguments: str) -> bytes:
    """
    Read Git metadata or staged bytes using fixed operations and distinct arguments.

    Args:
        root (Path): Existing repository root.
        *arguments (str): Fixed operation and validated path parameters.

    Returns:
        bytes: Git output, without printing stderr that might contain sensitive paths.

    Raises:
        ValueError: Git fails or exceeds the bounded timeout.
    """
    try:
        result = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("Could not read the repository for the privacy scan") from None

    if result.returncode:
        raise ValueError("Could not read the repository for the privacy scan")

    return result.stdout


def scan(root: Path, *, staged: bool = False, terms: Sequence[str] = (), paths: Sequence[str] = ()) -> tuple[Finding, ...]:
    """
    Scan repository source or exact staged content, refusing opaque files and escaping links.

    Args:
        root (Path): Git checkout; normal mode includes untracked, nonignored files.
        staged (bool): Read the complete index, ignoring unstaged working-tree replacements.
        terms (Sequence[str]): Additional sensitive literals from a private file.
        paths (Sequence[str]): Optional repository-relative files selecting a subset of the discovered sources.

    Returns:
        tuple[Finding, ...]: Redacted, stable findings; binary and unreadable files fail closed.

    Raises:
        ValueError: Repository access fails or selected files are not in the scan scope.
    """
    root = root.resolve()
    listing = (
        _git(root, "ls-files", "-z", "--cached") if staged else _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    )
    envelopes = set(_ENVELOPES)
    names = sorted({name.decode("utf-8", errors="surrogateescape") for name in listing.split(b"\0") if name})
    if CONFIG in names:
        # Ownership policy must come from the same snapshot as the bytes being checked.
        configuration = _git(root, "show", f":{CONFIG}") if staged else (root / CONFIG).read_bytes()
        envelopes.update(file_path(name) for name in parse_config(configuration).managed_files)

    if paths:
        if not set(paths).issubset(names):
            raise ValueError("Selected paths must be tracked or nonignored repository-relative files")

        names = sorted(set(paths))

    findings: list[Finding] = []

    for name in names:
        path_hits = scan_text(name, terms)
        label = "path-sha256:" + hashlib.sha256(name.encode(errors="surrogateescape")).hexdigest()[:16] if path_hits else name
        findings.extend(Finding(label, 0, rule) for _, rule in path_hits)
        path = root / name

        # Symlinks are inspected as targets, not followed outside the checkout.
        try:
            if staged:
                data = _git(root, "show", f":{name}")
            elif path.is_symlink():
                data = str(path.readlink()).encode()
            elif not path.exists():
                continue
            elif not path.resolve().is_relative_to(root) or path.stat().st_size > (MAX_BYTES * 2 if name in envelopes else 5 * 1024 * 1024):
                findings.append(Finding(label, 0, "unscannable-file"))
                continue
            else:
                data = path.read_bytes()

            # Only configured encrypted transport paths accept opaque content, with a closed envelope schema.
            if name in envelopes:
                validate_envelope(data)
                continue

            if len(data) > 5 * 1024 * 1024 or b"\0" in data:
                findings.append(Finding(label, 0, "unscannable-file"))
                continue

            content = data.decode("utf-8")
        except (OSError, UnicodeError, ValueError, ValidationError):
            findings.append(Finding(label, 0, "unscannable-file"))
            continue

        findings.extend(Finding(label, line, rule) for line, rule in scan_text(content, terms))

    return tuple(findings)


def validate_envelope(data: bytes) -> None:
    """
    Inspect an opaque transport contract without decrypting or treating ciphertext as source text.

    Args:
        data (bytes): JSON encrypted collection envelope.

    Returns:
        None: Only recognized fields, recipient identity, and bounded base64 encodings are present.

    Raises:
        ValueError: A transport field is invalid; signatures are checked separately before decryption.
    """
    if len(data) > MAX_BYTES * 2:
        raise ValueError("Oversized encrypted envelope")

    value = structure(json.loads(data), Envelope)

    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", value.repository)
        or not re.fullmatch(r"[a-f0-9]{64}", value.encryption_fingerprint)
        or len(base64.b64decode(value.wrapped_key, validate=True)) < 384
        or len(base64.b64decode(value.nonce, validate=True)) != 12
        or len(base64.b64decode(value.ciphertext, validate=True)) < 16
    ):
        raise ValueError("Invalid encrypted envelope")
