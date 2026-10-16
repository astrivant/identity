"""
Keep domain canonicality separate from the configured envelope's resource budget.
"""

from __future__ import annotations

import pytest
from witful.exceptions import NativeError
from witful.native import codec
from witful.native.values import pack, unpack


def test_large_admitted_domain_round_trip_preserves_configured_budget() -> None:
    """
    Reproduce a valid graph-sized domain that exceeds the default scalar count.

    Returns:
        None: Explicit decoder limits govern admission; domain conversion never silently restores smaller defaults.
    """
    original = {"nodes": [{"name": str(index), "line": index, "weight": 0.5} for index in range(12_000)]}
    tagged = pack(original)
    with pytest.raises(NativeError):
        codec.encode(tagged)
    limits = codec.Limits(bytes=8 * 1024 * 1024, items=1_000_000)
    encoded = codec.encode(tagged, limits)
    assert unpack(codec.decode(encoded, limits)) == original
    with pytest.raises(NativeError):
        codec.decode(encoded)


@pytest.mark.parametrize("value", [[3, "0x1p0"], [3, "nan"], [2, True], [2, 2**63], [6, {1: [0]}], [False]])
def test_domain_conversion_still_rejects_noncanonical_values(value: object) -> None:
    """
    Preserve scalar, key and canonical floating-point constraints without a second binary encoding.

    Args:
        value (object): Malformed or noncanonical tagged representation.

    Returns:
        None: Resource-budget separation does not relax value semantics.
    """
    with pytest.raises(NativeError):
        unpack(value)


def test_domain_conversion_bounds_recursive_inputs() -> None:
    """
    Reject cycles even when a caller bypasses the binary decoder.

    Returns:
        None: Malformed nested values produce the native diagnostic instead of unbounded recursion.
    """
    value: list[object] = [5, []]
    value[1] = [value]
    with pytest.raises(NativeError):
        unpack(value)
