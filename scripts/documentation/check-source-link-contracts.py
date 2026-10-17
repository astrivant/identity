"""
Exercise source-link boundary regressions immediately after the compiler's lint pass.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def main() -> int:
    """
    Run the owned documentation contracts once in the locked project environment.

    Returns:
        int: Pytest status, including collection failures; no parallel worker matrix is started.
    """
    root = Path(__file__).resolve().parents[2]
    return int(pytest.main(["-c", str(root / "pyproject.toml"), "-n", "0", "-q", str(root / "tests/documentation")]))


if __name__ == "__main__":
    raise SystemExit(main())
