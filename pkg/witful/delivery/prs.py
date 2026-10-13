"""
Order pull requests and prepare signed, reviewable rebases without merging them.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from .common import branch_name, checks, commit, destination, git, publish, read, remote_head, run, save, signing, text


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
        rows (list[dict[str, object]]): Open PR metadata.
        dependencies (dict[str, object]): Explicit PR-number keys mapped to prerequisite-number arrays.

    Returns:
        list[dict[str, object]]: Stable review order retaining source metadata.

    Raises:
        ValueError: Dependencies are missing, cyclic, or ambiguous.
    """
    by_number = {number(row["number"]): row for row in rows}
    heads = {text(row["headRefName"]): number(row["number"]) for row in rows if not row["isCrossRepository"]}
    if len(by_number) != len(rows) or len(heads) != sum(not row["isCrossRepository"] for row in rows):
        raise ValueError("Duplicate PR numbers or ambiguous branch heads")
    required: dict[int, set[int]] = {key: set() for key in by_number}
    for key, row in by_number.items():
        parent = heads.get(text(row["baseRefName"]))
        if parent is not None:
            required[key].add(parent)
    for dependency_key, value in dependencies.items():
        identifier = int(dependency_key)
        if identifier not in required or not isinstance(value, list):
            raise ValueError("Dependency keys must name open PRs with prerequisite arrays")
        for item in value:
            dependency = number(item)
            if dependency not in by_number:
                raise ValueError("A prerequisite is not in the open PR inventory; inspect its state")
            required[identifier].add(dependency)
    result: list[dict[str, object]] = []
    while required:
        ready = [key for key, parents in required.items() if not parents]
        if not ready:
            raise ValueError("PR dependencies contain a cycle")
        selected = min(
            ready,
            key=lambda key: (
                number(by_number[key]["additions"]) + number(by_number[key]["deletions"]),
                number(by_number[key]["changedFiles"]),
                key,
            ),
        )
        result.append(by_number[selected])
        del required[selected]
        for parents in required.values():
            parents.discard(selected)
    return result


def inventory(root: Path, dependencies: dict[str, object]) -> list[dict[str, object]]:
    """
    Fetch current PR metadata in one bounded GitHub CLI request.

    Args:
        root (Path): Selected existing repository.
        dependencies (dict[str, object]): Reviewed extra dependencies, never inferred from arbitrary mentions.

    Returns:
        list[dict[str, object]]: Ordered rows including links, drafts, body intent, and check evidence.

    Raises:
        ValueError: The response is malformed or potentially truncated.
    """
    fields = (
        "number,title,url,headRefName,headRefOid,baseRefName,baseRefOid,isCrossRepository,"
        "additions,deletions,changedFiles,isDraft,body,reviewDecision,statusCheckRollup"
    )
    value: object = json.loads(
        run(root, "gh", "pr", "list", "--repo", "github.com/" + destination(root), "--state", "open", "--limit", "1000", "--json", fields)
    )
    if not isinstance(value, list) or len(value) >= 1000:
        raise ValueError("Invalid or capped PR inventory; narrow the project outside this helper")
    rows: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Invalid PR row")
        rows.append({str(key): field for key, field in item.items()})
    return ordered(rows, dependencies)


def prepare(root: Path, identifier: int, old_base: str, worktree: Path, receipt: Path) -> dict[str, object]:
    """
    Prepare one PR on its current remote base, retaining conflicts and an immutable recovery reference.

    Args:
        root (Path): Existing source checkout, whose index is untouched.
        identifier (int): Same-repository feature PR selected by the caller.
        old_base (str): Original replay boundary captured before any parent rewrite.
        worktree (Path): New isolated worktree path.
        receipt (Path): New receipt outside the worktree.

    Returns:
        dict[str, object]: Prepared receipt; publication is a separate reviewed step.

    Raises:
        ValueError: The PR, source boundary, signing, or rebase is unsuitable.
    """
    repository = destination(root)
    selected = [row for row in inventory(root, {}) if number(row["number"]) == identifier]
    if len(selected) != 1 or selected[0]["isCrossRepository"]:
        raise ValueError("Select one open same-repository PR")
    row = selected[0]
    branch = branch_name(root, text(row["headRefName"]))
    default = run(root, "gh", "repo", "view", "github.com/" + repository, "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name")
    if branch in (default, "main", "master"):
        raise ValueError("Refusing to rewrite an integration branch")
    base_branch = branch_name(root, text(row["baseRefName"]))
    git(root, "fetch", "--no-tags", "origin", branch, base_branch)
    original = commit(root, text(row["headRefOid"]))
    if remote_head(root, branch) != original:
        raise ValueError("PR head changed during preparation")
    base = commit(root, remote_head(root, base_branch))
    previous = commit(root, old_base)
    git(root, "merge-base", "--is-ancestor", previous, original)
    signing(root)
    state: dict[str, object] = {
        "kind": "pr",
        "repository": repository,
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
    head = commit(root, "HEAD")
    if reviewed_head != head:
        raise ValueError("Review the exact candidate SHA before publishing")
    for name in ("rebase-merge", "rebase-apply"):
        if Path(git(root, "rev-parse", "--git-path", name)).exists():
            raise ValueError("Finish the retained rebase before publication")
    if remote_head(root, text(state["base_branch"])) != state["base"]:
        raise ValueError("PR base moved; prepare and review against its new head")
    git(root, "merge-base", "--is-ancestor", text(state["base"]), head)
    checks(root, commands)
    if commit(root, "HEAD") != head:
        raise ValueError("Validation changed HEAD")
    for revision in git(root, "rev-list", text(state["base"]) + ".." + head).splitlines():
        git(root, "verify-commit", revision)
    publish(root, text(state["repository"]), text(state["branch"]), text(state["original"]), head)
    state.update(status="published", head=head)
    save(receipt, state)
    return state
