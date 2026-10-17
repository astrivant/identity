"""
Provide synthetic test cases for the subprocess-level matrix plugin contract.
"""

from __future__ import annotations

import pytest


@pytest.mark.parametrize("value", [1, 2, 3, 4])
def test_case(value: int) -> None:
    """
    Execute bounded synthetic work and one explicit skip.

    Args:
        value (int): Deterministic case identifier.

    Returns:
        None: The last case reports a skip rather than fabricated execution evidence.
    """
    if value == 4:
        pytest.skip("Synthetic unavailable capability")
    assert value > 0
