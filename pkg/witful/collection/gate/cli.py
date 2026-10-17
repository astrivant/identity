"""
Select index, revision, or outgoing-history checks for local hooks and explicit CI use.
"""

from __future__ import annotations

import os
import re
import sys
from typing import TYPE_CHECKING

from witful.collection.gate.check import Checker
from witful.collection.gate.git import history, snapshot
from witful.exceptions import ArtifactGateError

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping


def push_ranges(value: str) -> tuple[tuple[str | None, str], ...]:
    """
    Parse every native Git pre-push update, including tags and deletion-only pushes.

    Args:
        value (str): Native hook stdin containing local ref/OID and remote ref/OID columns.

    Returns:
        tuple[tuple[str | None, str], ...]: Nondeleted destination updates; new refs have no excluded baseline.
    """
    ranges: list[tuple[str | None, str]] = []
    for line in value.splitlines():
        fields = line.rsplit(maxsplit=3)
        if len(fields) != 4 or any(not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", fields[index]) for index in (1, 3)):
            raise ArtifactGateError("Invalid native Git pre-push input")
        _, new, _, old = fields
        if set(new) != {"0"}:
            ranges.append((None if set(old) == {"0"} else old, new))
    return tuple(ranges)


def execute(args: argparse.Namespace, environment: Mapping[str, str] | None = None) -> None:
    """
    Resolve hook context once and fail before publication on any unverified snapshot.

    Args:
        args (argparse.Namespace): Shared collection subparser arguments.
        environment (Mapping[str, str] | None): Explicit pre-commit context, or the process environment.

    Returns:
        None: All selected snapshots passed; no Git refs, index entries, files or keys were changed.
    """
    env = os.environ if environment is None else environment
    if args.from_ref and not args.to_ref:
        raise ArtifactGateError("--from-ref requires --to-ref")
    checker = Checker(args.key_dir)
    if args.staged:
        checker.check(snapshot(args.checkout))
        print("Staged collection artifact policy and encryption verified.")
        return
    if args.revision:
        checker.check(snapshot(args.checkout, args.revision))
        print("Committed collection artifact policy and encryption verified.")
        return
    if args.git_pre_push:
        # Native stdin preserves every ref. The pre-commit framework supplies one selected ref through its environment.
        value = sys.stdin.read(1024 * 1024 + 1)
        if len(value) > 1024 * 1024:
            raise ArtifactGateError("Push reference input exceeds its byte limit")
        ranges = push_ranges(value)
    elif args.pre_push:
        new = env.get("PRE_COMMIT_TO_REF") or env.get("PRE_COMMIT_LOCAL_BRANCH")
        if not new:
            raise ArtifactGateError("No push reference context; use --revision or explicit --to-ref for a manual check")
        ranges = ((env.get("PRE_COMMIT_FROM_REF"), new),)
    else:
        if not args.to_ref:
            raise ArtifactGateError("Supply --to-ref for an outgoing history check")
        ranges = ((args.from_ref, args.to_ref),)
    revisions = history(args.checkout, ranges, args.max_commits) if ranges else ()
    for revision in revisions:
        checker.check(snapshot(args.checkout, revision))
    print(f"Collection artifact policy and encryption verified across {len(revisions)} outgoing commit snapshots.")
