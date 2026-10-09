"""
Derive package version from a stable tag and record immutable build provenance.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path


def main() -> None:
    """
    Update tag build metadata before packaging without changing the source commit.

    Returns:
        None: SOURCE.json identifies the Git revision and optional version tag.

    Raises:
        ValueError: A tag does not use the supported stable version format.
    """
    tag = os.environ.get("RELEASE_TAG", "")

    if tag:
        if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
            raise ValueError("Expected vMAJOR.MINOR.PATCH")

        subprocess.run(["poetry", "version", tag[1:]], check=True)

    commit = subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    Path("dist").mkdir(exist_ok=True)
    Path("dist/SOURCE.json").write_text(json.dumps({"commit": commit, "tag": tag or None}, indent=2) + "\n")


if __name__ == "__main__":
    main()
