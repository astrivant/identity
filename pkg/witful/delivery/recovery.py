"""
Recover small coherent file batches before larger payloads using independently verified Git pushes.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from uuid import uuid4

from .common import arrays, branch_name, checks, commit, destination, git, publish, read, remote_head, save, signing, text


def batches(root: Path, source: str, selected: list[list[str]]) -> list[list[str]]:
    """
    Sort explicitly coherent file groups by total source blob bytes, with deterministic ties.

    Args:
        root (Path): Source repository.
        source (str): Immutable source commit.
        selected (list[list[str]]): Explicit reviewed path groups; one path per group gives strict file-size order.

    Returns:
        list[list[str]]: Smallest-first groups, without splitting dependent files.

    Raises:
        ValueError: Paths repeat, escape the tree, or name directories, submodules, or symbolic links.
    """
    measured: list[tuple[int, tuple[str, ...]]] = []
    seen: set[str] = set()
    for group in selected:
        size = 0
        for name in group:
            path = PurePosixPath(name)
            if (
                name in seen
                or path.is_absolute()
                or ".." in path.parts
                or ".git" in path.parts
                or name != path.as_posix()
                or not path.parts
                or any(character in name for character in "\n\r\0")
            ):
                raise ValueError("Select distinct literal repository-relative file paths")
            seen.add(name)
            entry = git(root, "ls-tree", source, "--", name)
            if not entry.startswith(("100644 blob ", "100755 blob ")):
                raise ValueError("Recovery supports existing regular source files only")
            size += int(git(root, "cat-file", "-s", source + ":" + name))
        measured.append((size, tuple(sorted(group))))
    return [list(group) for _, group in sorted(measured)]


def plan(root: Path, specification: Path, worktree: Path, receipt: Path) -> dict[str, object]:
    """
    Create a reviewable small-first plan from immutable source and a currently published base.

    Args:
        root (Path): Existing repository with the committed source files.
        specification (Path): JSON with source, base_branch, recovery branch, and coherent batches.
        worktree (Path): New isolated worktree to create only when applying the plan.
        receipt (Path): New private receipt outside that worktree.

    Returns:
        dict[str, object]: Planned groups bound to exact source and base commits.

    Raises:
        ValueError: Destination exists, base is absent, or the plan is unsuitable.
    """
    spec = read(specification)
    repository = destination(root)
    branch = branch_name(root, text(spec["branch"]))
    if not branch.startswith("recovery/"):
        raise ValueError("Use an explicit recovery/ branch after reviewing its CI triggers")
    base_branch = branch_name(root, text(spec["base_branch"]))
    if branch == base_branch or remote_head(root, branch):
        raise ValueError("Select a new recovery branch distinct from the published base")
    git(root, "fetch", "--no-tags", "origin", base_branch)
    base = commit(root, remote_head(root, base_branch))
    source = commit(root, text(spec["source"]))
    groups = batches(root, source, arrays(spec["batches"]))
    if worktree.exists() or receipt.resolve().is_relative_to(worktree.resolve()):
        raise ValueError("Use a new worktree and a receipt outside it")
    selected = {name for group in groups for name in group}
    changed = set(git(root, "diff", "--name-only", "--no-renames", "-z", base, source).split("\0")) - {""}
    if not selected <= changed:
        raise ValueError("Every selected file must differ from the published base")
    state: dict[str, object] = {
        "kind": "recovery",
        "root": str(root.resolve()),
        "repository": repository,
        "branch": branch,
        "base": base,
        "source": source,
        "worktree": str(worktree.resolve()),
        "batches": groups,
        "omitted": sorted(changed - selected),
        "completed": [],
        "pending": "",
        "status": "planned",
    }
    save(receipt, state, create=True)
    return state


def apply(receipt: Path, commands: list[list[str]]) -> dict[str, object]:
    """
    Resume signed batch publication without replaying previously acknowledged pushes.

    Args:
        receipt (Path): Reviewed plan retained across interruptions.
        commands (list[list[str]]): Validation commands appropriate for every coherent intermediate tree.

    Returns:
        dict[str, object]: Receipt with independently verified commits and any deliberately omitted paths.

    Raises:
        ValueError: State, origin, checks, signing, or a concurrent remote write prevents progress.
    """
    state = read(receipt)
    if state.get("kind") != "recovery":
        raise ValueError("Expected a recovery receipt")
    source_root, root = Path(text(state["root"])), Path(text(state["worktree"]))
    repository, branch = text(state["repository"]), text(state["branch"])
    if destination(source_root) != repository or not branch.startswith("recovery/"):
        raise ValueError("Recovery destination changed")
    groups = arrays(state["batches"])
    completed = state["completed"]
    if not isinstance(completed, list) or len(completed) > len(groups):
        raise ValueError("Malformed progress receipt")
    accepted = [text(item) for item in completed]
    signing(source_root)
    if not root.exists():
        if accepted or state["pending"]:
            raise ValueError("The pending worktree is missing; recover it before retrying")
        git(source_root, "update-ref", "refs/witful/delivery/" + uuid4().hex, text(state["source"]), "0" * 40)
        git(source_root, "worktree", "add", "--detach", str(root), text(state["base"]))
    if destination(root) != repository:
        raise ValueError("Worktree origin changed")
    while len(accepted) < len(groups):
        previous = accepted[-1] if accepted else text(state["base"])
        pending = text(state["pending"])
        expected = accepted[-1] if accepted else ""
        if remote_head(root, branch) not in ({expected, pending} if pending else {expected}):
            raise ValueError("Recovery branch changed; do not overwrite another writer")
        if not pending:
            if commit(root, "HEAD") != previous or git(root, "status", "--porcelain", "--untracked-files=all"):
                raise ValueError("Interrupted local changes remain; inspect them before resuming")
            git(root, "restore", "--source", text(state["source"]), "--staged", "--worktree", "--", *groups[len(accepted)])
            # Keep the baseline as parent; never push the source commit that already contains the large blob.
            git(root, "commit", "-S", "-m", f"Checkpoint recovery batch {len(accepted) + 1} of {len(groups)}")
            pending = commit(root, "HEAD")
            state.update(pending=pending, status="validating")
            save(receipt, state)
        if commit(root, "HEAD") != pending:
            raise ValueError("Pending candidate changed; inspect the receipt before resuming")
        checks(root, commands)
        if commit(root, "HEAD") != pending:
            raise ValueError("Validation changed HEAD")
        publish(root, repository, branch, expected, pending)
        accepted.append(pending)
        state.update(completed=accepted, pending="", status="partial")
        save(receipt, state)
    # Even a completed retry must verify the currently observed remote, not trust an old receipt.
    if remote_head(root, branch) != accepted[-1]:
        raise ValueError("Completed recovery ref changed; prior receipt is historical evidence only")
    state["status"] = "selected-batches-published"
    save(receipt, state)
    return state
