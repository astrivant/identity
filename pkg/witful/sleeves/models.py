"""
Define local session ownership and explicit reconciliation state.
"""

from __future__ import annotations

from attrs import frozen


@frozen
class Sleeve:
    """
    Identify one isolated instance and its immutable starting revision.

    Attributes:
        branch (str): Unique remote backup branch.
        base (str): Integration branch, normally main.
        remote (str): Explicit private origin.
        repository (str): GitHub owner/repository bound at creation.
        started_at (str): UTC creation timestamp.
        base_commit (str): Remote integration revision at creation.
        worktree (str): Isolated Git worktree path.
        directory (str): Private directory containing worktree and optional plaintext sources.
        keys (str | None): Existing external key directory for encrypted collections.
        source_digest (str | None): Last checkpointed plaintext archive digest, never published.
        closed_commit (str | None): Remote integration revision observed to contain this sleeve.
    """

    branch: str
    base: str
    remote: str
    repository: str
    started_at: str
    base_commit: str
    worktree: str
    directory: str
    keys: str | None = None
    source_digest: str | None = None
    closed_commit: str | None = None


class SleeveError(ValueError):
    """
    Report an actionable lifecycle failure without private Git output or source values.
    """
