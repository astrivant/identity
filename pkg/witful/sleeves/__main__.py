"""
Run the packaged sleeve CLI in a separate process for bounded shutdown work.
"""

from __future__ import annotations

from witful.sleeves.cli import main

raise SystemExit(main())
