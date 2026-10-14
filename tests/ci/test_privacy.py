"""
Keep the public asset review bound to one path, digest and Git snapshot.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from checks.privacy import LOGO, findings

ROOT = Path(__file__).resolve().parents[2]


def test_reviewed_logo_does_not_exempt_other_binary_content(tmp_path: Path) -> None:
    """
    Accept reviewed bytes while refusing modifications, renamed copies and staged drift.

    Args:
        tmp_path (Path): Disposable Git repository.

    Returns:
        None: Only the exact approved snapshot is exempted from opaque-file rejection.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / LOGO
    path.parent.mkdir(parents=True)
    reviewed = (ROOT / LOGO).read_bytes()
    path.write_bytes(reviewed)
    assert findings(tmp_path) == ()
    path.write_bytes(reviewed + b"\x00changed")
    subprocess.run(["git", "-C", str(tmp_path), "add", LOGO], check=True)
    path.write_bytes(reviewed)
    assert findings(tmp_path) == ()
    assert findings(tmp_path, staged=True)[0].rule == "unscannable-file"
    subprocess.run(["git", "-C", str(tmp_path), "add", LOGO], check=True)
    assert findings(tmp_path, staged=True) == ()
    (tmp_path / "unreviewed.png").write_bytes(reviewed)
    assert findings(tmp_path)[0].path == "unreviewed.png"
