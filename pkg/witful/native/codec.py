"""
Implement the bounded deterministic CBOR profile shared by native records and encrypted envelopes.
"""

from __future__ import annotations

import hashlib
import io

import cbor2
from attrs import frozen

from witful.exceptions import NativeError

__all__ = ["Limits", "decode", "digest", "encode"]


@frozen
class Limits:
    """
    Bound encoded input and decoded work before admitting a native value.

    Attributes:
        bytes (int): Maximum encoded bytes per record, independent of collection size.
        items (int): Maximum total scalar/container/key nodes in one value.
        depth (int): Maximum container nesting, including the root.
    """

    bytes: int = 4 * 1024 * 1024
    items: int = 100_000
    depth: int = 32

    def __attrs_post_init__(self) -> None:
        """
        Reject nonpositive budgets instead of silently disabling a bound.

        Returns:
            None: The configured budgets are positive integers.

        Raises:
            NativeError: A budget has an invalid type or range.
        """
        if any(type(value) is not int or value < 1 for value in (self.bytes, self.items, self.depth)):
            raise NativeError("invalid")


def validate(value: object, limits: Limits) -> None:
    """
    Admit only exact scalar types, string-keyed maps and lists, without coercion or normalization.

    Args:
        value (object): Candidate native value.
        limits (Limits): Explicit work and size budget.

    Returns:
        None: The complete value belongs to the version-one data model.

    Raises:
        NativeError: Unsupported types, recursion, node count or scalar size violate the profile.
    """
    pending = [(value, 1)]
    visited = 0
    size = 0
    while pending:
        item, depth = pending.pop()
        visited += 1
        size += 1
        if depth > limits.depth or visited > limits.items or size > limits.bytes:
            raise NativeError("invalid")
        if item is None or type(item) is bool:
            continue
        if type(item) is int:
            if not -(2**63) <= item < 2**63:
                raise NativeError("invalid")
        elif type(item) is str:
            size += len(item.encode("utf-8"))
        elif type(item) is bytes:
            size += len(item)
        elif type(item) is list:
            if len(item) + len(pending) + visited > limits.items:
                raise NativeError("invalid")
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is dict:
            if len(item) * 2 + len(pending) + visited > limits.items or any(type(key) is not str for key in item):
                raise NativeError("invalid")
            for key, child in item.items():
                pending.extend(((key, depth + 1), (child, depth + 1)))
        else:
            raise NativeError("invalid")
    if size > limits.bytes:
        raise NativeError("invalid")


DEFAULT_LIMITS = Limits()


def encode(value: object, limits: Limits = DEFAULT_LIMITS) -> bytes:
    """
    Encode one admitted value using RFC 8949 length-first deterministic ordering.

    Args:
        value (object): Version-one value with exact strings preserved and no floating-point or tagged values.
        limits (Limits): Positive resource ceilings, also applied before encoding.

    Returns:
        bytes: Definite-length canonical CBOR, with shortest integer encodings.

    Raises:
        NativeError: The value or output exceeds the profile or budget.
    """
    try:
        validate(value, limits)
        result = cbor2.dumps(value, canonical=True)
        if len(result) > limits.bytes:
            raise NativeError("invalid")
        return result
    except (ValueError, UnicodeError, cbor2.CBOREncodeError, RecursionError):
        raise NativeError("invalid") from None


def preflight(payload: bytes, limits: Limits) -> None:
    """
    Reject tags before the library can invoke its built-in semantic decoders.

    Args:
        payload (bytes): Size-bounded input, still untrusted.
        limits (Limits): Structural work limits.

    Returns:
        None: Only supported definite scalar/container forms reach the maintained decoder.

    Raises:
        NativeError: A tag, unsupported scalar, truncated value or structural budget is encountered.
    """
    # This syntax guard never constructs domain values; cbor2 owns decoding and canonical encoding.
    pending = [1]
    offset = 0
    visited = 0
    while pending:
        if pending[-1] == 0:
            pending.pop()
            continue
        pending[-1] -= 1
        visited += 1
        if visited > limits.items or len(pending) > limits.depth or offset >= len(payload):
            raise NativeError("invalid")
        initial = payload[offset]
        offset += 1
        major, argument = initial >> 5, initial & 31
        if major == 6 or (major == 7 and initial not in (0xF4, 0xF5, 0xF6)) or argument > 27:
            raise NativeError("invalid")
        if argument >= 24:
            width = 1 << (argument - 24)
            if offset + width > len(payload):
                raise NativeError("invalid")
            argument = int.from_bytes(payload[offset : offset + width], "big")
            offset += width
        if major in (2, 3):
            offset += argument
            if offset > len(payload):
                raise NativeError("invalid")
        elif major in (4, 5):
            children = argument * (2 if major == 5 else 1)
            if children + visited > limits.items:
                raise NativeError("invalid")
            pending.append(children)
    if offset != len(payload):
        raise NativeError("invalid")


def decode(payload: bytes, limits: Limits = DEFAULT_LIMITS) -> object:
    """
    Reject ambiguous representations before a native record can enter validation or hashing.

    Args:
        payload (bytes): One bounded CBOR value, with no trailing bytes.
        limits (Limits): Resource budget matching the caller's declared profile.

    Returns:
        object: Validated native value; callers still enforce the closed domain schema.

    Raises:
        NativeError: Malformed, noncanonical, duplicate, indefinite, tagged or unsupported input.
    """
    if not payload or len(payload) > limits.bytes:
        raise NativeError("invalid")
    try:
        preflight(payload, limits)
        stream = io.BytesIO(payload)
        decoder = cbor2.CBORDecoder(stream, max_depth=limits.depth, allow_duplicate_keys=False, allow_indefinite=False)
        value: object = decoder.decode()
        # Re-encoding rejects accepted semantic tags, overlong integers and alternative map orderings too.
        if stream.tell() != len(payload) or encode(value, limits) != payload:
            raise NativeError("invalid")
        return value
    except (ValueError, UnicodeError, cbor2.CBORDecodeError, RecursionError):
        raise NativeError("invalid") from None


def digest(value: object, limits: Limits = DEFAULT_LIMITS) -> bytes:
    """
    Identify logical bytes independently of randomized encrypted representations.

    Args:
        value (object): Schema-validated native value.
        limits (Limits): Codec resource budget.

    Returns:
        bytes: Domain-separated SHA-256; meaningful plaintext digests must themselves remain protected.
    """
    return hashlib.sha256(b"witful-native-cbor-v1\x00" + encode(value, limits)).digest()
