"""
Expose a read-only PII gate for source checks, pre-commit, and CI.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from attrs import asdict

from sapience.privacy.scanner import scan

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    """
    Report only finding locations and detector IDs, keeping sensitive matches out of logs.

    Args:
        argv (Sequence[str] | None): Explicit arguments or the current process arguments.

    Returns:
        int: Zero when clear, one for findings, or parser exit two for an incomplete scan.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["scan"])
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--staged", action="store_true", help="Inspect the complete index, not unstaged working-tree replacements")
    parser.add_argument(
        "--terms-file", type=Path, default=os.environ.get("SAPIENCE_PII_TERMS_FILE"), help="Private UTF-8 literals, one per line"
    )
    args = parser.parse_args(argv)

    try:
        terms = tuple(line.strip() for line in args.terms_file.read_text().splitlines() if line.strip()) if args.terms_file else ()
        findings = scan(args.repo, staged=args.staged, paths=args.paths, terms=terms)
    except (OSError, UnicodeError, ValueError):
        parser.exit(2, "PII scan incomplete: check repository access, paths, and the private terms file.\n")

    for finding in findings:
        print(json.dumps(asdict(finding), separators=(",", ":")))

    print(json.dumps({"findings": len(findings), "complete": True}, separators=(",", ":")))
    return int(bool(findings))
