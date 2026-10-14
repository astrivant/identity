"""
Scan repository sources while verifying the exact reviewed public logo bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from attrs import asdict
from witful.privacy.scanner import Finding, scan

LOGO = "docs/assets/identity-logo.png"
# Visually reviewed graph mark from main; no PNG metadata. Changed bytes need a new review.
LOGO_SHA256 = "d3e695291f15683e502537538c2b153a20acd51099ab060293ef01052e10ae47"


def findings(root: Path, *, staged: bool = False) -> tuple[Finding, ...]:
    """
    Retain every detector finding except an exact reviewed opaque asset match.

    Args:
        root (Path): Repository whose source or complete index is inspected.
        staged (bool): Select the same staged bytes as the underlying scanner.

    Returns:
        tuple[Finding, ...]: Findings without matched source values.
    """
    result = scan(root, staged=staged)
    if not any(item.path == LOGO and item.rule == "unscannable-file" for item in result):
        return result

    # An unstaged replacement cannot authorize different bytes already in the index.
    if staged:
        data = subprocess.run(["git", "-C", str(root), "show", f":{LOGO}"], capture_output=True, check=True, timeout=30).stdout
    else:
        path = root / LOGO
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            return result
        data = path.read_bytes()

    if hashlib.sha256(data).hexdigest() != LOGO_SHA256:
        return result
    return tuple(item for item in result if not (item.path == LOGO and item.rule == "unscannable-file"))


def main() -> int:
    """
    Apply the repository asset review alongside the unchanged general privacy scanner.

    Returns:
        int: Zero for clear sources, one for findings; incomplete scans raise an error.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args()
    result = findings(Path.cwd(), staged=args.staged)
    for item in result:
        print(json.dumps(asdict(item)))
    print(json.dumps({"findings": len(result), "complete": True}))
    return int(bool(result))


if __name__ == "__main__":
    raise SystemExit(main())
