"""
Represent domain scalars losslessly inside the deterministic CBOR profile without ambiguous sentinel maps.
"""

from __future__ import annotations

import math

from witful.exceptions import NativeError
from witful.native import codec

__all__ = ["pack", "unpack"]


def pack(value: object, depth: int = 0) -> object:
    """
    Encode every value with an explicit type tag, including finite binary64 values as canonical hexadecimal text.

    Args:
        value (object): JSON-compatible domain value; tuples are normalized only at this explicit adapter boundary.
        depth (int): Current nesting used to reject recursive or excessively deep input.

    Returns:
        object: Unambiguous CBOR-profile value; original source bytes must be archived separately.
    """
    if depth > 24:
        raise NativeError("invalid")
    if value is None:
        return [0]
    if type(value) is bool:
        return [1, value]
    if type(value) is int:
        return [2, value]
    if type(value) is float:
        if not math.isfinite(value):
            raise NativeError("invalid")
        return [3, value.hex()]
    if type(value) is str:
        return [4, value]
    if isinstance(value, (list, tuple)):
        return [5, [pack(item, depth + 1) for item in value]]
    if type(value) is dict and all(type(key) is str for key in value):
        return [6, {key: pack(item, depth + 1) for key, item in value.items()}]
    raise NativeError("invalid")


def unpack(value: object) -> object:
    """
    Decode only canonical tagged values, rejecting unknown tags and alternate numeric representations.

    Args:
        value (object): Bounded value already admitted by the CBOR decoder.

    Returns:
        object: Original finite JSON-compatible domain value.
    """
    if not isinstance(value, list) or not value or type(value[0]) is not int:
        raise NativeError("invalid")
    tag = value[0]
    if value == [0]:
        return None
    if len(value) != 2:
        raise NativeError("invalid")
    payload = value[1]
    result: object
    if tag == 1 and type(payload) is bool:
        result = payload
    elif tag == 2 and type(payload) is int:
        result = payload
    elif tag == 3 and type(payload) is str:
        try:
            result = float.fromhex(payload)
        except ValueError:
            raise NativeError("invalid") from None
    elif tag == 4 and type(payload) is str:
        result = payload
    elif tag == 5 and isinstance(payload, list):
        result = [unpack(item) for item in payload]
    elif tag == 6 and isinstance(payload, dict):
        result = {key: unpack(item) for key, item in payload.items()}
    else:
        raise NativeError("invalid")
    if codec.encode(pack(result)) != codec.encode(value):
        raise NativeError("invalid")
    return result
