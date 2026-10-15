"""
Define closed encrypted metadata contracts independently of physical backend and key representation.
"""

from __future__ import annotations

from typing import TypeVar

from attrs import frozen
from jsonschema.exceptions import ValidationError

from witful.exceptions import NativeError
from witful.knowledge.contracts import structure

T = TypeVar("T")

__all__ = ["Pointer", "Revision", "Ref", "Frontier", "Receipt", "parse"]


@frozen
class Pointer:
    """
    Bind an immutable semantic revision to one independently authenticated ciphertext representation.

    Attributes:
        record (str): Stable logical UUID used as authenticated record context.
        object (str): Random ciphertext object UUID.
        kind (int): Closed native record discriminator.
        digest (str): Hexadecimal ciphertext digest, retained within the encrypted manifest.
    """

    record: str
    object: str
    kind: int
    digest: str


@frozen
class Revision:
    """
    Retain ordered native ancestry without rewriting an imported domain journal's linear hash chain.

    Attributes:
        id (str): Immutable logical revision UUID.
        domain (str): Registered version-one domain schema.
        payload (Pointer): Individually encrypted typed domain object.
        parents (tuple[str, ...]): Ordered native revision UUIDs.
        operation (str): Stable authoring operation UUID.
        recorded (str): Actual UTC recording time, distinct from domain timestamps.
        source (Pointer | None): Exact imported bytes when an explicit import supplies them.
    """

    id: str
    domain: str
    payload: Pointer
    parents: tuple[str, ...]
    operation: str
    recorded: str
    source: Pointer | None = None


@frozen
class Ref:
    """
    Keep meaningful names and branch relationships inside the authenticated frontier.

    Attributes:
        name (str): Human branch or tag name, never a relational key.
        revision (str): Logical target UUID.
        generation (int): Monotonic per-ref version including delete and recreation through retained history.
        immutable (bool): Whether this ref is a retained tag.
    """

    name: str
    revision: str
    generation: int
    immutable: bool = False


@frozen
class Frontier:
    """
    Publish all logical refs through one CAS root while keeping each domain revision independently addressable.

    Attributes:
        version (int): Closed manifest schema version.
        previous (Pointer | None): Retained prior frontier, enabling complete history and restore.
        refs (tuple[Ref, ...]): Ordered logical refs with unique names.
        revisions (tuple[Pointer, ...]): Authorized immutable revision metadata, not plaintext domain records.
        archives (tuple[Pointer, ...]): Retained original representations and migration manifests.
        outbox (tuple[Pointer, ...]): Durable pending projection intents.
    """

    version: int = 1
    previous: Pointer | None = None
    refs: tuple[Ref, ...] = ()
    revisions: tuple[Pointer, ...] = ()
    archives: tuple[Pointer, ...] = ()
    outbox: tuple[Pointer, ...] = ()


@frozen
class Receipt:
    """
    Preserve the exact logical request binding without exposing low-entropy semantic hashes to storage.

    Attributes:
        version (int): Receipt schema version.
        operation (str): Stable caller operation UUID.
        request (str): Domain-separated semantic request digest, encrypted at rest.
        epoch (int): Admitted backend authority epoch.
        policy (str): Admitted policy revision UUID.
        generation (int): Commit-order watermark assigned by CAS.
        root (Pointer): Exact prepared frontier representation.
        outcome (str): Durable storage acknowledgment, never implied remote publication.
    """

    version: int
    operation: str
    request: str
    epoch: int
    policy: str
    generation: int
    root: Pointer
    outcome: str


def parse(value: object, model: type[T]) -> T:
    """
    Validate a closed metadata model while suppressing plaintext validation details.

    Args:
        value (object): Authenticated decoded metadata.
        model (type[T]): Package-owned schema.

    Returns:
        T: Strictly typed metadata.
    """
    try:
        return structure(value, model)
    except (ValidationError, ValueError, TypeError):
        raise NativeError("invalid") from None
