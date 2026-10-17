"""
Run checkout-owned documentation maintenance from the development environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == "__main__":
    from documentation.source_links import main

    raise SystemExit(main())
