"""
Prove redaction, staged-source ownership, and known detector boundaries with synthetic inputs.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest
from sapience.privacy.cli import main
from sapience.privacy.scanner import scan, scan_text

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import CaptureFixture


@pytest.mark.parametrize(
    "text,rule",
    [
        ("sample" + "@" + "synthetic-company.dev", "email"),
        ("/Users/" + "synthetic-owner/project", "personal-home"),
        ("C:\\Users\\" + "synthetic-owner\\project", "personal-home"),
        ("555" + "-010-1234", "phone"),
        ("123" + "-45-6789", "government-id"),
        ("https://www.linkedin.com/" + "in/synthetic-member", "profile-url"),
        ("-----BEGIN " + "PRIVATE KEY-----", "private-key"),
    ],
)
def test_known_patterns(text: str, rule: str) -> None:
    """
    Recognize each declared detector without storing real personal fixtures.

    Args:
        text (str): Constructed synthetic pattern instance.
        rule (str): Expected detector identifier.

    Returns:
        None: Findings preserve the correct line and contain no matched value.
    """
    assert (2, rule) in scan_text("header\n" + text)
    assert text not in repr(scan_text(text))


def test_explicit_literals_and_safe_examples() -> None:
    """
    Accept documented synthetic domains while applying private deny terms consistently.

    Returns:
        None: Literal checks are case-insensitive and regex syntax is not interpreted.
    """
    assert scan_text("sample@example.org /home/runner/work") == ()
    assert scan_text("Some Private Literal", ["private literal"]) == ((1, "deny-term"),)
    assert scan_text("abc", ["a.*"]) == ()


def test_scan_uses_exact_index_and_redacts_sensitive_paths(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    """
    Prevent unstaged replacements from hiding staged findings and avoid disclosing filename matches.

    Args:
        tmp_path (Path): Temporary Git checkout.
        capsys (CaptureFixture[str]): Redacted CLI output capture.

    Returns:
        None: The index and worktree are scanned independently and opaque content blocks publication.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / "fixture.txt"
    path.write_text("a synthetic forbidden literal\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "fixture.txt"], check=True)
    path.write_text("clean unstaged replacement\n")
    assert scan(tmp_path, terms=["forbidden literal"]) == ()
    assert scan(tmp_path, staged=True, terms=["forbidden literal"])[0].rule == "deny-term"

    secret_name = "forbidden" + "-filename.txt"
    (tmp_path / secret_name).write_text("clean\n")
    findings = scan(tmp_path, terms=["forbidden"])
    assert findings[0].path.startswith("path-sha256:")
    assert secret_name not in repr(findings)
    (tmp_path / "opaque.bin").write_bytes(b"\0\xff")
    assert any(item.rule == "unscannable-file" for item in scan(tmp_path))
    assert main(["scan", "--repo", str(tmp_path)]) == 1
    assert "forbidden literal" not in capsys.readouterr().out


def test_symlinks_do_not_read_outside_the_repository(tmp_path: Path) -> None:
    """
    Read link text while avoiding traversal into unrelated private files.

    Args:
        tmp_path (Path): Temporary checkout and external test file owner.

    Returns:
        None: External contents are not scanned or exposed through a symlink.
    """
    root = tmp_path / "source"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    external = tmp_path / "outside.txt"
    external.write_text("forbidden sentinel")
    (root / "link").symlink_to(external)
    assert scan(root, terms=["forbidden sentinel"]) == ()
