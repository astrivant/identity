"""
Exercise worker output and lifetime bounds with real local processes.
"""

from __future__ import annotations

import os
import sys

import pytest
from witful.codegraph.worker import run
from witful.exceptions import NativeError


def test_bounded_bidirectional_exchange() -> None:
    """
    Transfer beyond pipe capacity without deadlock or changing exact bytes.

    Returns:
        None: The bounded process preserves complete input/output under backpressure.
    """
    data = b"synthetic" * 20000
    result = run((sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"), data, os.environ, 5, len(data))
    assert result == data


@pytest.mark.parametrize("program", ["import os; os.write(1,b'x'*8192)", "import time; time.sleep(60)"])
def test_output_or_lifetime_exhaustion(program: str) -> None:
    """
    Kill and reap a worker when either resource limit is exceeded.

    Args:
        program (str): Synthetic output overflow or nonterminating worker.

    Returns:
        None: No partial successful response escapes either boundary.
    """
    with pytest.raises(NativeError, match="incomplete"):
        run((sys.executable, "-c", program), b"", os.environ, 0.2, 1024)
