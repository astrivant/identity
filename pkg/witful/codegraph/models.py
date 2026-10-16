"""
Define inert revision-bound graph records and independently approved enrollment settings.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Literal

from attrs import frozen

from witful.exceptions import NativeError
from witful.native.context import identifier

Coverage = Literal["indexed", "file-only", "excluded", "unsupported", "sdk-omitted", "worker-control", "non-text", "pending"]


@frozen
class Extension:
    """
    Bind a custom suffix to a language validated by the actual pinned SDK.

    Attributes:
        suffix (str): Canonical lowercase dot-prefixed suffix.
        language (str): Upstream language identifier, never executable parser code.
    """

    suffix: str
    language: str


@frozen
class Enrollment:
    """
    Bind one engineer's approved codebase to a separate native cryptographic scope.

    Attributes:
        tenant (str): Independently provisioned tenant UUID.
        extension (str): Dedicated native identity/key scope UUID, never the learning identity's scope.
        owner (str): Engineer's owning learning identity UUID, retained as protected lineage only.
        subject (str): Admitted runtime's verified TLS certificate fingerprint.
        repository (str): Canonical approved workspace root on the admitted host.
        image (str): Locally built and reviewed worker image content ID.
        excluded (tuple[str, ...]): Explicit relative glob exclusions, applied before indexing.
        retention (str): Reviewed retention policy reference; no automatic deletion follows.
        source_bytes (int): Maximum admitted source bytes across the snapshot.
        files (int): Maximum tracked paths inspected.
        seconds (int): Maximum worker lifetime.
        memory_mb (int): Worker memory including its nonswappable temporary filesystem.
        profile (Literal["python", "sdk"]): Legacy Python selection or the upstream SDK's complete language detector.
        worker_bytes (int): Maximum serialized worker input and output bytes.
        extensions (tuple[Extension, ...]): Explicit custom suffix mappings; the SDK validates language support.
    """

    tenant: str
    extension: str
    owner: str
    subject: str
    repository: str
    image: str
    excluded: tuple[str, ...] = ()
    retention: str = "retain-until-reviewed-removal"
    source_bytes: int = 8 * 1024 * 1024
    files: int = 2048
    seconds: int = 60
    memory_mb: int = 512
    profile: Literal["python", "sdk"] = "python"
    worker_bytes: int = 16 * 1024 * 1024
    extensions: tuple[Extension, ...] = ()

    def __attrs_post_init__(self) -> None:
        """
        Reject ambiguous scopes, mutable image tags and unbounded worker settings.

        Returns:
            None: The declaration is valid, not independently authorized.
        """
        for value in (self.tenant, self.extension, self.owner):
            identifier(value)
        if self.extension == self.owner or not self.repository.startswith("/") or not self.retention:
            raise NativeError("invalid")
        if not digest(self.subject) or not self.image.startswith("sha256:") or not digest(self.image[7:]):
            raise NativeError("invalid")
        if any(
            type(value) is not int or value < 1
            for value in (self.source_bytes, self.files, self.seconds, self.memory_mb, self.worker_bytes)
        ):
            raise NativeError("invalid")
        if self.profile not in {"python", "sdk"}:
            raise NativeError("invalid")
        if self.extensions and self.profile != "sdk":
            raise NativeError("invalid")
        if len({item.suffix for item in self.extensions}) != len(self.extensions):
            raise NativeError("invalid")
        for item in self.extensions:
            if (
                re.fullmatch(r"\.[a-z0-9][a-z0-9_-]{0,63}", item.suffix) is None
                or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", item.language) is None
            ):
                raise NativeError("invalid")
        for pattern in self.excluded:
            relative(pattern)


@frozen
class Source:
    """
    Retain exact indexed bytes only in the admitted worker's memory.

    Attributes:
        path (str): Repository-relative source path.
        text (str): Exact UTF-8 text; never interpreted as instructions.
        digest (str): SHA-256 of original bytes.
    """

    path: str
    text: str
    digest: str


@frozen
class File:
    """
    Record indexed or visibly omitted files inside the encrypted manifest.

    Attributes:
        path (str): Repository-relative path.
        digest (str): Original Git blob ID for omitted files or SHA-256 of indexed bytes.
        coverage (Coverage): Explicit selection, extraction, omission or encoding status; pending is transient only.
        language (str): SDK-detected language, empty for legacy or unclassified files.
    """

    path: str
    digest: str
    coverage: Coverage
    language: str = ""


@frozen
class Node:
    """
    Qualify SDK-local symbol identity through its containing immutable generation.

    Attributes:
        id (str): SDK-local symbol ID, not a stable cross-revision identity.
        name (str): Exact symbol name.
        path (str): Approved repository-relative path.
        kind (str): SDK symbol classification.
        start (int): One-based source start line.
        end (int): Inclusive source end line.
    """

    id: str
    name: str
    path: str
    kind: str
    start: int
    end: int


@frozen
class Edge:
    """
    Preserve extractor-qualified relationships without treating them as authority.

    Attributes:
        source (str): Generation-local source node.
        target (str): Generation-local target node.
        kind (str): SDK relationship classification.
        provenance (str): Upstream parser/resolver provenance or explicit unknown.
    """

    source: str
    target: str
    kind: str
    provenance: str


@frozen
class Graph:
    """
    Store one complete authenticated graph generation without learned-state side effects.

    Attributes:
        enrollment (Enrollment): Exact approved repository, owner, runtime and filters.
        generation (str): Immutable build UUID.
        revision (str): Exact Git commit, never a branch label.
        tree (str): Git tree identity for freshness checks.
        files (tuple[File, ...]): Coverage and exact source qualifications.
        nodes (tuple[Node, ...]): Bounded inert SDK projection.
        edges (tuple[Edge, ...]): Bounded relationships with provenance.
        indexer (str): Locked SDK version reported by the worker.
        unresolved (int): Unresolved references reported by the SDK.
        omitted_untracked (bool): Whether Git reported untracked files omitted from this build.
        schema (Literal["repository-codegraph/0.1.0"]): Closed extension schema.
        language (Literal["python", "sdk"]): Source selection profile; per-file language is reported by the SDK.
    """

    enrollment: Enrollment
    generation: str
    revision: str
    tree: str
    files: tuple[File, ...]
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    indexer: str
    unresolved: int
    omitted_untracked: bool
    schema: Literal["repository-codegraph/0.1.0"] = "repository-codegraph/0.1.0"
    language: Literal["python", "sdk"] = "python"


def digest(value: str, lengths: tuple[int, ...] = (64,)) -> bool:
    """
    Recognize canonical hexadecimal hashes without coercion.

    Args:
        value (str): Candidate hash.
        lengths (tuple[int, ...]): Admitted digest sizes.

    Returns:
        bool: Whether the input is canonical lowercase hexadecimal.
    """
    return len(value) in lengths and all(char in "0123456789abcdef" for char in value)


def relative(value: str) -> str:
    """
    Reject path aliases, traversal and nested repository control files.

    Args:
        value (str): Candidate portable relative path.

    Returns:
        str: Unchanged canonical safe path.
    """
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or str(path) != value
        or any(part in {"..", ".git", ".codegraph"} for part in path.parts)
        or "\\" in value
        or any(ord(char) < 32 for char in value)
    ):
        raise NativeError("invalid")
    return value


def validate(graph: Graph) -> None:
    """
    Reject malformed source references and incomplete relationship endpoints.

    Args:
        graph (Graph): Strictly decoded generation.

    Returns:
        None: Structural consistency holds, without implying complete static analysis.
    """
    identifier(graph.generation)
    if not digest(graph.revision, (40, 64)) or not digest(graph.tree, (40, 64)) or graph.unresolved < 0:
        raise NativeError("invalid")
    if graph.language != graph.enrollment.profile:
        raise NativeError("invalid")
    for item in graph.files:
        if item.coverage == "pending":
            raise NativeError("incomplete")
        relative(item.path)
        if not digest(item.digest, (40, 64)):
            raise NativeError("invalid")
    paths = {relative(item.path) for item in graph.files if item.coverage in {"indexed", "file-only"}}
    ids = {node.id for node in graph.nodes}
    if len(ids) != len(graph.nodes) or len({item.path for item in graph.files}) != len(graph.files):
        raise NativeError("invalid")
    for node in graph.nodes:
        if not node.id or node.path not in paths or node.start < 1 or node.end < node.start:
            raise NativeError("invalid")
    if any(edge.source not in ids or edge.target not in ids for edge in graph.edges):
        raise NativeError("invalid")
