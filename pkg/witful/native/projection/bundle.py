"""
Prepare exact Git object bytes from an already encrypted sidecar without remote I/O or invented historical attribution.
"""

from __future__ import annotations

from attrs import field, frozen

from witful.exceptions import NativeError
from witful.native import codec
from witful.native.context import identifier
from witful.native.original_git import canonical
from witful.native.wire import binary, integer, mapping


def framed(kind: str, payload: bytes) -> bytes:
    """
    Use Git's canonical object identity framing; envelope SHA-256/signatures remain the security authenticator.

    Args:
        kind (str): Explicit Git blob, tree or commit type.
        payload (bytes): Exact immutable object payload.

    Returns:
        bytes: Git type, length, NUL and payload.
    """
    if kind not in {"blob", "tree", "commit"}:
        raise NativeError("invalid")
    return kind.encode("ascii") + b" " + str(len(payload)).encode("ascii") + b"\0" + payload


@frozen
class Bundle:
    """
    Retain every byte required to retry one projection without re-encryption or new commit metadata.

    Attributes:
        blob (bytes): Signed encrypted native-history sidecar, not plaintext domain content.
        tree (bytes): Exactly one native.cbor entry.
        commit (bytes): Honest new exporter attribution, fixed actual time and expected parent.
    """

    blob: bytes = field(repr=False)
    tree: bytes = field(repr=False)
    commit: bytes = field(repr=False)

    def objects(self) -> tuple[tuple[str, str, bytes], ...]:
        """
        Select canonical insertion order and recompute each Git OID from the exact retained bytes.

        Returns:
            tuple[tuple[str, str, bytes], ...]: Type, Git OID and payload for blob, tree and commit.
        """
        return tuple(
            (kind, canonical(framed(kind, payload), "sha1"), payload)
            for kind, payload in (
                ("blob", self.blob),
                ("tree", self.tree),
                ("commit", self.commit),
            )
        )

    def encode(self, limits: codec.Limits) -> bytes:
        """
        Serialize the closed exact-candidate object set before its first remote request.

        Args:
            limits (codec.Limits): Complete candidate size/structure bound.

        Returns:
            bytes: Versioned canonical CBOR containing only already encrypted data and approved Git metadata.
        """
        return codec.encode({"version": 1, "blob": self.blob, "tree": self.tree, "commit": self.commit}, limits)

    @classmethod
    def decode(cls, payload: bytes, limits: codec.Limits) -> Bundle:
        """
        Recover exact object bytes without accepting additional objects, files or format versions.

        Args:
            payload (bytes): Durable prepared bytes.
            limits (codec.Limits): Explicit decoder bound.

        Returns:
            Bundle: Structurally decoded candidate; expected parent/attribution validation remains separate.
        """
        value = mapping(codec.decode(payload, limits), {"version", "blob", "tree", "commit"})
        if integer(value["version"]) != 1:
            raise NativeError("unsupported")
        return cls(binary(value["blob"]), binary(value["tree"]), binary(value["commit"]))


def prepare(blob: bytes, operation: str, parent: str | None, author: str, email: str, recorded: int) -> Bundle:
    """
    Construct a deterministic honest new Git commit before contacting any remote, including an explicitly selected parent OID.

    Args:
        blob (bytes): Final signed encrypted native sidecar bytes, reused unchanged.
        operation (str): Stable opaque projection intent UUID.
        parent (str | None): Exact expected remote head, or explicit create-if-absent.
        author (str): Reviewed exporter identity, never an imported historical author.
        email (str): Reviewed exporter contact.
        recorded (int): Actual export time in UTC epoch seconds, fixed across retries.

    Returns:
        Bundle: Canonical blob, tree and commit bytes, independently checked by real Git in contract tests.
    """
    identifier(operation)
    if parent is not None and (len(parent) != 40 or any(char not in "0123456789abcdef" for char in parent)):
        raise NativeError("invalid")
    if type(recorded) is not int or recorded < 0 or not author or not email or len(author) + len(email) > 512:
        raise NativeError("invalid")
    if any(ord(char) < 32 or ord(char) == 127 or char in "<>" for char in author + email) or any(char.isspace() for char in email):
        raise NativeError("invalid")
    if not author.isascii() or not email.isascii():
        raise NativeError("invalid")
    blob_id = canonical(framed("blob", blob), "sha1")
    tree = b"100644 native.cbor\0" + bytes.fromhex(blob_id)
    tree_id = canonical(framed("tree", tree), "sha1")
    identity = f"{author} <{email}> {recorded} +0000\n"
    commit = (
        f"tree {tree_id}\n"
        + (f"parent {parent}\n" if parent is not None else "")
        + "author "
        + identity
        + "committer "
        + identity
        + f"\nNative encrypted projection {operation}\n"
    ).encode("ascii")
    return Bundle(blob, tree, commit)


def validate(bundle: Bundle, operation: str, parent: str | None, author: str, email: str, recorded: int) -> None:
    """
    Require exactly the approved sidecar tree, expected parent and honest metadata before a gateway can publish anything.

    Args:
        bundle (Bundle): Recovered exact object bytes.
        operation (str): Expected opaque intent.
        parent (str | None): Independently selected compare-and-set boundary.
        author (str): Approved exporter identity.
        email (str): Approved exporter contact.
        recorded (int): Original prepared export time.

    Returns:
        None: Every tree/commit byte matches the bounded supported projection profile.
    """
    if bundle != prepare(bundle.blob, operation, parent, author, email, recorded):
        raise NativeError("invalid")
