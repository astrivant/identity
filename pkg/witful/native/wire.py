"""
Serialize prepared ciphertext transactions for durable recovery without persisting plaintext domain data.
"""

from __future__ import annotations

from witful.exceptions import NativeError
from witful.native import codec
from witful.native.storage import Batch, Head, Object

__all__ = ["encode_batch", "decode_batch", "mapping", "sequence", "text", "binary", "integer"]


def mapping(value: object, keys: set[str]) -> dict[str, object]:
    """
    Admit an exact string-keyed map.

    Args:
        value (object): Untrusted decoded value.
        keys (set[str]): Complete expected field set.

    Returns:
        dict[str, object]: Closed map with no unknown or missing fields.
    """
    if not isinstance(value, dict) or set(value) != keys:
        raise NativeError("invalid")
    return {str(key): item for key, item in value.items()}


def sequence(value: object) -> list[object]:
    """
    Admit a list without coercing another container.

    Args:
        value (object): Untrusted decoded value.

    Returns:
        list[object]: Array elements.
    """
    if not isinstance(value, list):
        raise NativeError("invalid")
    return list(value)


def text(value: object) -> str:
    """
    Admit text without coercion.

    Args:
        value (object): Untrusted scalar.

    Returns:
        str: Exact input string.
    """
    if type(value) is not str:
        raise NativeError("invalid")
    return value


def binary(value: object) -> bytes:
    """
    Admit binary data without decoding text.

    Args:
        value (object): Untrusted scalar.

    Returns:
        bytes: Exact binary input.
    """
    if type(value) is not bytes:
        raise NativeError("invalid")
    return value


def integer(value: object) -> int:
    """
    Admit an integer while excluding booleans.

    Args:
        value (object): Untrusted scalar.

    Returns:
        int: Exact integer input.
    """
    if type(value) is not int:
        raise NativeError("invalid")
    return value


def encode_batch(batch: Batch, limits: codec.Limits) -> bytes:
    """
    Retain every prepared byte needed after a crash, including the receipt and outbox.

    Args:
        batch (Batch): Sealed immutable candidate.
        limits (codec.Limits): Explicit aggregate recovery budget.

    Returns:
        bytes: Version-one binary recovery package containing ciphertext and opaque routing only.
    """
    return codec.encode(
        {
            "v": 1,
            "operation": batch.operation,
            "expected": [batch.expected.generation, batch.expected.root, batch.expected.digest],
            "objects": [[item.id, item.payload] for item in (batch.root, batch.receipt, *batch.objects, *batch.outbox)],
            "count": len(batch.objects),
        },
        limits,
    )


def decode_batch(data: bytes, limits: codec.Limits) -> Batch:
    """
    Recover a closed candidate and reject malformed counts before selecting ownership groups.

    Args:
        data (bytes): Previously persisted prepared transaction.
        limits (codec.Limits): Same explicit recovery budget used on admission.

    Returns:
        Batch: Exact replay candidate, never resealed on retry.
    """
    value = mapping(codec.decode(data, limits), {"v", "operation", "expected", "objects", "count"})
    if integer(value["v"]) != 1:
        raise NativeError("unsupported")
    expected = sequence(value["expected"])
    if len(expected) != 3:
        raise NativeError("invalid")
    head = Head(integer(expected[0]), None if expected[1] is None else text(expected[1]), binary(expected[2]))
    objects: list[Object] = []
    for item in sequence(value["objects"]):
        pair = sequence(item)
        if len(pair) != 2:
            raise NativeError("invalid")
        objects.append(Object(text(pair[0]), binary(pair[1])))
    count = integer(value["count"])
    if count < 0 or len(objects) < count + 2:
        raise NativeError("invalid")
    return Batch(text(value["operation"]), head, objects[0], tuple(objects[2 : 2 + count]), objects[1], tuple(objects[2 + count :]))
