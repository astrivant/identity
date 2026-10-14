"""
Order pull and merge requests and prepare signed, reviewable rebases without merging them.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import networkx as nx

from .common import branch_name, checks, commit, destination, git, publish, read, remote_head, save, saved_destination, signing, text
from .providers import backend


def number(value: object) -> int:
    """
    Accept nonnegative integer counts and PR identifiers.

    Args:
        value (object): Untrusted JSON scalar.

    Returns:
        int: Validated integer.

    Raises:
        ValueError: The value is negative, Boolean, or nonnumeric.
    """
    if type(value) is not int or value < 0:
        raise ValueError("Expected a nonnegative integer")
    return value


def ordered(rows: list[dict[str, object]], dependencies: dict[str, object]) -> list[dict[str, object]]:
    """
    Topologically order base relationships and explicitly reviewed dependencies, smallest ready diff first.

    Args:
        rows (list[dict[str, object]]): Normalized PR and MR metadata.
        dependencies (dict[str, object]): Qualified request keys or unique numeric aliases mapped to prerequisite arrays.

    Returns:
        list[dict[str, object]]: Stable review order retaining source metadata.

    Raises:
        ValueError: Dependencies are missing, cyclic, or ambiguous.
    """
    by_key = {text(row.get("key", str(number(row["number"])))): row for row in rows}
    heads = {
        (text(row.get("repository", "")), text(row["headRefName"])): key for key, row in by_key.items() if not row["isCrossRepository"]
    }
    if len(by_key) != len(rows) or len(heads) != sum(not row["isCrossRepository"] for row in rows):
        raise ValueError("Duplicate request identifiers or ambiguous branch heads")
    graph: nx.DiGraph[str, dict[str, object], dict[str, object]] = nx.DiGraph()
    graph.add_nodes_from(by_key)
    for key, row in by_key.items():
        parent = heads.get((text(row.get("repository", "")), text(row["baseRefName"])))
        if parent is not None:
            graph.add_edge(parent, key)

    # Numeric aliases are usable only when they identify exactly one request across selected projects.
    def resolve(value: object) -> str:
        """
        Resolve a qualified request key or an unambiguous numeric shorthand.

        Args:
            value (object): Reviewed dependency reference.

        Returns:
            str: Unique inventory key.
        """
        reference = str(value) if type(value) is int else text(value)
        if reference in by_key:
            return reference
        matches = [key for key, row in by_key.items() if str(row["number"]) == reference]
        if len(matches) != 1:
            raise ValueError("Dependency is ambiguous or not in the open request inventory; use a qualified key")
        return matches[0]

    for key, value in dependencies.items():
        target = resolve(key)
        if not isinstance(value, list):
            raise ValueError("Dependency prerequisites must be arrays")
        for item in value:
            graph.add_edge(resolve(item), target)

    def size(key: str) -> tuple[bool, int, int, str, int]:
        """
        Sort known small changes first without treating missing GitLab counts as zero.

        Args:
            key (str): Qualified request identifier.

        Returns:
            tuple[bool, int, int, str, int]: Stable size and identity tie breakers.
        """
        row = by_key[key]
        missing = any(row[field] is None for field in ("additions", "deletions", "changedFiles"))
        lines = 0 if missing else number(row["additions"]) + number(row["deletions"])
        files = 0 if missing else number(row["changedFiles"])
        return missing, lines, files, text(row.get("repository", "")), number(row["number"])

    try:
        return [by_key[key] for key in nx.lexicographical_topological_sort(graph, key=size)]
    except nx.NetworkXUnfeasible:
        raise ValueError("Request dependencies contain a cycle") from None


def inventory(root: Path, dependencies: dict[str, object], remotes: tuple[str, ...] = ("origin",)) -> list[dict[str, object]]:
    """
    Collect a complete bounded review inventory from one or both hosting providers.

    Args:
        root (Path): Selected existing repository.
        dependencies (dict[str, object]): Explicit reviewed prerequisites.
        remotes (tuple[str, ...]): Selected remote names with optional provider qualifiers.

    Returns:
        list[dict[str, object]]: Globally ordered rows with qualified identities and provider evidence.
    """
    rows: list[dict[str, object]] = []
    repositories = [destination(root, remote) for remote in remotes]
    if not repositories or len({repository.key for repository in repositories}) != len(repositories):
        raise ValueError("Select distinct provider projects")
    for repository in repositories:
        with backend(repository) as provider:
            rows.extend(provider.requests())
    return ordered(rows, dependencies)


def prepare(root: Path, identifier: int, old_base: str, worktree: Path, receipt: Path, remote: str = "origin") -> dict[str, object]:
    """
    Prepare one PR on its current remote base, retaining conflicts and an immutable recovery reference.

    Args:
        root (Path): Existing source checkout, whose index is untouched.
        identifier (int): Same-repository feature PR selected by the caller.
        old_base (str): Original replay boundary captured before any parent rewrite.
        worktree (Path): New isolated worktree path.
        receipt (Path): New receipt outside the worktree.
        remote (str): One explicitly selected provider-qualified remote.

    Returns:
        dict[str, object]: Prepared receipt; publication is a separate reviewed step.

    Raises:
        ValueError: The PR, source boundary, signing, or rebase is unsuitable.
    """
    repository = destination(root, remote)
    selected = [row for row in inventory(root, {}, (remote,)) if number(row["number"]) == identifier]
    if len(selected) != 1 or selected[0]["isCrossRepository"]:
        raise ValueError("Select one open same-repository PR or MR")
    row = selected[0]
    branch = branch_name(root, text(row["headRefName"]))
    with backend(repository) as provider:
        default = provider.default_branch()
    if branch in (default, "main", "master"):
        raise ValueError("Refusing to rewrite an integration branch")
    base_branch = branch_name(root, text(row["baseRefName"]))
    git(root, "fetch", "--no-tags", repository.remote, branch, base_branch)
    original = commit(root, text(row["headRefOid"]))
    if remote_head(root, branch, repository.remote) != original:
        raise ValueError("PR head changed during preparation")
    base = commit(root, remote_head(root, base_branch, repository.remote))
    previous = commit(root, old_base)
    git(root, "merge-base", "--is-ancestor", previous, original)
    signing(root)
    state: dict[str, object] = {
        "kind": "pr",
        "repository": repository.data(),
        "branch": branch,
        "base_branch": base_branch,
        "original": original,
        "old_base": previous,
        "base": base,
        "worktree": str(worktree.resolve()),
        "status": "preparing",
    }
    if worktree.exists() or receipt.resolve().is_relative_to(worktree.resolve()):
        raise ValueError("Use a new worktree and a receipt outside it")
    save(receipt, state, create=True)
    git(root, "update-ref", "refs/witful/delivery/" + uuid4().hex, original, "0" * 40)
    git(root, "worktree", "add", "--detach", str(worktree), original)
    # Resolve both endpoints in the source checkout, never interpret HEAD in the child.
    if base != previous:
        git(worktree, "rebase", "--gpg-sign", "--rebase-merges", "--reapply-cherry-picks", "--empty=stop", "--onto", base, previous)
    state["status"] = "review"
    state["head"] = commit(worktree, "HEAD")
    save(receipt, state)
    return state


def publish_pr(receipt: Path, reviewed_head: str, commands: list[list[str]]) -> dict[str, object]:
    """
    Publish a reviewed candidate after semantic checks, all hooks, ancestry, and signing verification.

    Args:
        receipt (Path): Preparation receipt, retained after conflicts or interruption.
        reviewed_head (str): Exact full SHA whose range-diff the caller reviewed.
        commands (list[list[str]]): Relevant test command vectors.

    Returns:
        dict[str, object]: Remotely verified receipt, without claiming CI passed.

    Raises:
        ValueError: Review is stale, the base moved, or a rebase remains unfinished.
    """
    state = read(receipt)
    if state.get("kind") != "pr":
        raise ValueError("Expected a PR receipt")
    root = Path(text(state["worktree"]))
    repository = saved_destination(root, state["repository"])
    head = commit(root, "HEAD")
    if reviewed_head != head:
        raise ValueError("Review the exact candidate SHA before publishing")
    for name in ("rebase-merge", "rebase-apply"):
        if Path(git(root, "rev-parse", "--git-path", name)).exists():
            raise ValueError("Finish the retained rebase before publication")
    if remote_head(root, text(state["base_branch"]), repository.remote) != state["base"]:
        raise ValueError("PR base moved; prepare and review against its new head")
    git(root, "merge-base", "--is-ancestor", text(state["base"]), head)
    checks(root, commands)
    if commit(root, "HEAD") != head:
        raise ValueError("Validation changed HEAD")
    for revision in git(root, "rev-list", text(state["base"]) + ".." + head).splitlines():
        git(root, "verify-commit", revision)
    publish(root, repository, text(state["branch"]), text(state["original"]), head)
    state.update(status="published", head=head)
    save(receipt, state)
    return state
