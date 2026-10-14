"""
Bind generated view bytes to explicit source files and an immutable Git revision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def hashes(root: Path, patterns: Sequence[str], excluded: Path) -> dict[str, str]:
    """
    Hash every selected regular file, rejecting missing patterns and unsafe paths.

    Args:
        root (Path): Resolved repository directory.
        patterns (Sequence[str]): Explicit repository-relative file patterns.
        excluded (Path): Receipt excluded from its own digest map.

    Returns:
        dict[str, str]: Stable path-to-SHA256 mapping.

    Raises:
        ValueError: A pattern is unsafe, empty, or selects a symlink or non-file.
    """
    result: dict[str, str] = {}

    for pattern in patterns:
        if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise ValueError("Patterns must stay inside the repository")
        matches = sorted(root.glob(pattern))
        if not matches:
            raise ValueError(f"Required pattern has no files: {pattern}")

        for path in matches:
            if path == excluded:
                continue
            if (
                not path.is_file()
                or path.is_symlink()
                or any(parent.is_symlink() for parent in path.parents if parent != root)
                or not path.resolve().is_relative_to(root)
            ):
                raise ValueError(f"Expected an owned regular file: {path.relative_to(root)}")
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()

    return dict(sorted(result.items()))


def main(argv: Sequence[str] | None = None) -> int:
    """
    Write or verify a receipt without storing timestamps, absolute paths, or source contents.

    Args:
        argv (Sequence[str] | None): Explicit arguments or the process command line.

    Returns:
        int: Zero for a written or matching receipt; one for stale content.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source", action="append")
    parser.add_argument("--output", action="append")
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--revision")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--verify-receipt", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    receipt = root / args.receipt
    if args.receipt.is_absolute() or ".." in args.receipt.parts or receipt.is_symlink():
        parser.error("Receipt must be a repository-relative regular file")
    revision = args.revision or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    # Publication verifies the downloaded artifact against the checked-out source.
    if args.verify_receipt:
        data = json.loads(receipt.read_text())
        if data.get("version") != 1 or data.get("source_revision") != revision:
            return 1
        for field in ("sources", "outputs"):
            recorded = data.get(field)
            if not isinstance(recorded, dict) or not recorded or not all(isinstance(key, str) for key in recorded):
                return 1
            if hashes(root, tuple(recorded), receipt) != recorded:
                return 1
        return 0

    if not args.source or not args.output:
        parser.error("Rendering requires both --source and --output selections")
    payload = {
        "version": 1,
        "source_revision": revision,
        "sources": hashes(root, args.source, receipt),
        "outputs": hashes(root, args.output, receipt),
    }
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", *hashes(root, args.source, receipt)],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    source_state = "unversioned" if status.returncode else "working-tree" if status.stdout else "committed"
    payload["source_state"] = source_state
    content = json.dumps(payload, indent=2, sort_keys=True) + "\n"

    if args.check:
        return 0 if receipt.is_file() and receipt.read_text() == content else 1

    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
