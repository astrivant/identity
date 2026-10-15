"""
Detect explicit personal-data patterns without echoing matched values.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
from typing import TYPE_CHECKING, Literal

from attrs import frozen
from jsonschema import ValidationError

from witful.collection.models import CONFIG, MAX_BYTES, Envelope, file_path, parse_config
from witful.knowledge.contracts import structure

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

__all__ = ["Finding", "GapReason", "ScanGap", "ScanReport", "scan", "scan_report", "scan_text"]

GapReason = Literal["binary-content", "non-utf8-content", "encrypted-envelope", "read-error", "invalid-envelope", "file-too-large"]

_RULES = {
    "email": re.compile(r"\b[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[A-Z0-9-]+\.)+[A-Z]{2,}\b", re.I),
    "personal-home": re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+|[A-Z]:\\Users\\[A-Za-z0-9_.-]+"),
    "phone": re.compile(r"(?<![\w.])(?:\+\d{1,3}[ .-])?(?:\(\d{3}\)|\d{3})[ .-]\d{3}[ .-]\d{4}(?![\w.])"),
    "government-id": re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),
    "profile-url": re.compile(r"https?://(?:[a-z]+\.)?linkedin\.com/in/[^\s/\"<>]+", re.I),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
}
# npm scopes use @ as a namespace separator in these package paths, not as an email delimiter.
_NPM_REFERENCES = re.compile(
    r"(?<![A-Za-z0-9_/@])(?:node_modules/|https://registry\.npmjs\.org/)"
    r"@[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*(?=$|[/\"'\s),:])"
)
_SAFE_HOMES = {"/home/runner", "/home/witful"}
_SYNTHETIC_EMAIL_DOMAINS = {"example.com", "example.org", "example.net"}
_ENVELOPES = {"collection/sources.enc.json", "collection/figures.enc.json"}


@frozen
class Finding:
    """
    Locate a finding without retaining the sensitive match or its surrounding text.

    Attributes:
        path (str): Relative path, replaced by a digest label if its name is itself sensitive.
        line (int): One-based line number, or zero for filename matches.
        rule (str): Detector identifier, never its matched value.
    """

    path: str
    line: int
    rule: str


@frozen
class ScanGap:
    """
    Identify uninspected content without confusing it with a detected pattern.

    Attributes:
        path (str): Repository-relative or redacted digest label, as for findings.
        reason (GapReason): Bounded explanation without source data or exception details.
    """

    path: str
    reason: GapReason


@frozen
class ScanReport:
    """
    Keep detector evidence, unsupported content and inspection failures separate.

    Attributes:
        findings (tuple[Finding, ...]): Actual pattern matches in filenames or inspected text.
        skipped (tuple[ScanGap, ...]): Unsupported content or schema-validated encrypted envelopes.
        errors (tuple[ScanGap, ...]): Files that could not be read or validated within the scan contract.
    """

    findings: tuple[Finding, ...]
    skipped: tuple[ScanGap, ...]
    errors: tuple[ScanGap, ...]

    @property
    def complete(self) -> bool:
        """
        State whether every selected payload was inspected as text.

        Returns:
            bool: False for skipped content or inspection errors, even without findings.
        """
        return not self.skipped and not self.errors


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
    packages = tuple(match.span() for match in _NPM_REFERENCES.finditer(text))

    for rule, pattern in _RULES.items():
        for match in pattern.finditer(text):
            value = match.group()

            if rule == "personal-home" and value in _SAFE_HOMES:
                continue
            if rule == "email":
                if any(start <= match.start() and match.end() <= end for start, end in packages):
                    continue
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
    Return actual detections, preserving the finding-only Python interface.

    Args:
        root (Path): Git checkout; normal mode includes untracked, nonignored files.
        staged (bool): Read the complete index, ignoring unstaged working-tree replacements.
        terms (Sequence[str]): Additional sensitive literals from a private file.
        paths (Sequence[str]): Optional repository-relative files selecting a subset of discovered sources.

    Returns:
        tuple[Finding, ...]: Redacted matches only; use scan_report to inspect skipped content and coverage.

    Raises:
        ValueError: Repository access, path selection or file inspection fails.
        OSError: The collection configuration cannot be read.
    """
    report = scan_report(root, staged=staged, terms=terms, paths=paths)
    if report.errors:
        raise ValueError("PII scan incomplete: file inspection failed")
    return report.findings


def scan_report(root: Path, *, staged: bool = False, terms: Sequence[str] = (), paths: Sequence[str] = ()) -> ScanReport:
    """
    Scan filenames and UTF-8 source, reporting unsupported content separately from detections.

    Args:
        root (Path): Git checkout; normal mode includes untracked, nonignored files.
        staged (bool): Read the complete index, ignoring unstaged working-tree replacements.
        terms (Sequence[str]): Additional sensitive literals from a private file.
        paths (Sequence[str]): Optional repository-relative files selecting a subset of discovered sources.

    Returns:
        ScanReport: Stable redacted detections, skipped payloads and inspection errors.

    Raises:
        ValueError: Repository access fails or selected files are not in the scan scope.
        OSError: The collection configuration cannot be read.
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
    skipped: list[ScanGap] = []
    errors: list[ScanGap] = []

    for name in names:
        # Even unsupported payloads have their filenames inspected and redacted when sensitive.
        path_hits = scan_text(name, terms)
        label = "path-sha256:" + hashlib.sha256(name.encode(errors="surrogateescape")).hexdigest()[:16] if path_hits else name
        findings.extend(Finding(label, 0, rule) for _, rule in path_hits)
        path = root / name
        limit = MAX_BYTES * 2 if name in envelopes else 5 * 1024 * 1024

        # Symlinks are inspected as targets, never followed into unrelated private files.
        try:
            if staged:
                data = _git(root, "show", f":{name}")
            elif path.is_symlink():
                data = str(path.readlink()).encode()
            elif not path.resolve().is_relative_to(root):
                errors.append(ScanGap(label, "read-error"))
                continue
            elif path.stat().st_size > limit:
                errors.append(ScanGap(label, "file-too-large"))
                continue
            else:
                data = path.read_bytes()
        except (OSError, UnicodeError, ValueError):
            errors.append(ScanGap(label, "read-error"))
            continue

        if len(data) > limit:
            errors.append(ScanGap(label, "file-too-large"))
            continue

        # Validate managed transport without claiming ciphertext was checked for personal data.
        if name in envelopes:
            try:
                validate_envelope(data)
            except (ValueError, ValidationError):
                errors.append(ScanGap(label, "invalid-envelope"))
            else:
                skipped.append(ScanGap(label, "encrypted-envelope"))
            continue

        # Classification uses bytes, not extensions or a per-asset approval exception.
        if b"\0" in data:
            skipped.append(ScanGap(label, "binary-content"))
            continue
        try:
            content = data.decode("utf-8")
        except UnicodeError:
            skipped.append(ScanGap(label, "non-utf8-content"))
            continue
        findings.extend(Finding(label, line, rule) for line, rule in scan_text(content, terms))

    return ScanReport(tuple(findings), tuple(skipped), tuple(errors))


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
