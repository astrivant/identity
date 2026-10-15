"""
Check canonical byte vectors, budget failures and lossless deterministic native values.
"""

from __future__ import annotations

import pytest
from witful.exceptions import NativeError
from witful.native.codec import Limits, decode, digest, encode


@pytest.mark.parametrize(
    ("value", "hexadecimal"),
    [(None, "f6"), (True, "f5"), (-1, "20"), (24, "1818"), (b"\x00", "4100"), ({"b": 2, "a": 1}, "a2616101616202")],
)
def test_profile_vectors(value: object, hexadecimal: str) -> None:
    """
    Require stable RFC-compatible bytes and preserve the original value across decoding.

    Args:
        value (object): Independently specified small CBOR value.
        hexadecimal (str): Expected RFC 8949 representation, suitable for cross-language consumers.

    Returns:
        None: Encoding, decoding and semantic hashes agree on exact bytes.
    """
    original = repr(value)
    raw = bytes.fromhex(hexadecimal)
    assert encode(value) == raw
    assert decode(raw) == value
    assert encode(decode(raw)) == raw
    assert digest(value) == digest(decode(raw))
    assert repr(value) == original


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        bytes.fromhex("1800"),
        bytes.fromhex("9fff"),
        bytes.fromhex("a2616101616102"),
        bytes.fromhex("c001"),
        bytes.fromhex("f93c00"),
        bytes.fromhex("a2616202616101"),
        b"\x01\x02",
        b"\x61\xff",
    ],
)
def test_reject_ambiguous_input(payload: bytes) -> None:
    """
    Reject malformed or alternative encodings without retaining payload diagnostics.

    Args:
        payload (bytes): Invalid or noncanonical native representation.

    Returns:
        None: Every unsupported input has a bounded fixed error.
    """
    with pytest.raises(NativeError, match="^Native operation invalid$"):
        decode(payload)


@pytest.mark.parametrize("value", [1.0, 2**63, -(2**63) - 1, {1: "wrong-key"}, (1, 2), {1, 2}])
def test_reject_unsupported_values(value: object) -> None:
    """
    Refuse implicit type conversions and values outside the version-one profile.

    Args:
        value (object): Unsupported scalar or container.

    Returns:
        None: Unsupported values cannot acquire an accepted native digest.
    """
    with pytest.raises(NativeError):
        encode(value)


def test_budgets_and_exact_original_bytes() -> None:
    """
    Bound cyclic/oversized inputs while preserving historical bytes and exact Unicode sequences.

    Returns:
        None: Original bytes survive without normalization, and budget exhaustion fails closed.
    """
    cyclic: list[object] = []
    cyclic.append(cyclic)
    with pytest.raises(NativeError):
        encode(cyclic)
    for value, limits in [("large", Limits(bytes=3)), ([1, 2], Limits(items=2)), ([[1]], Limits(depth=2))]:
        with pytest.raises(NativeError):
            encode(value, limits)
    original = {"source": b'{ "value": 1 }\r\n', "text": "e\u0301"}
    assert decode(encode(original)) == original


def test_shared_cross_language_vectors() -> None:
    """
    Verify the same independent byte and hash fixtures consumed by the maintained JavaScript codec in CI.

    Returns:
        None: Python agrees with the language-neutral registry, including signed integer limits and exact Unicode bytes.
    """
    import json
    from pathlib import Path

    from witful.native.wire import mapping, sequence, text

    def materialize(value: object) -> object:
        """
        Recover fixture byte and integer wrappers without changing actual native values.

        Args:
            value (object): JSON fixture node.

        Returns:
            object: Exact value supported by the version-one native codec.
        """
        if isinstance(value, list):
            return [materialize(item) for item in value]
        if isinstance(value, dict):
            if set(value) == {"$bytes"}:
                return bytes.fromhex(text(value["$bytes"]))
            if set(value) == {"$integer"}:
                return int(text(value["$integer"]))
            return {key: materialize(item) for key, item in value.items()}
        return value

    values = mapping(json.loads((Path(__file__).parent / "resources/codec-v1.json").read_text()), {"profile", "source", "valid", "invalid"})
    for item in sequence(values["valid"]):
        vector = mapping(item, {"name", "value", "hex", "sha256"})
        value = materialize(vector["value"])
        assert encode(value).hex() == vector["hex"]
        assert decode(bytes.fromhex(text(vector["hex"]))) == value
        assert digest(value).hex() == vector["sha256"]
    for raw in sequence(values["invalid"]):
        with pytest.raises(NativeError, match="invalid"):
            decode(bytes.fromhex(text(raw)))
