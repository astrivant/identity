"""
Create isolated sleeves, back up named changes, and require remote integration before closure.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from attrs import evolve

from witful.collection.process import run
from witful.exceptions import SleeveError
from witful.sleeves import sources, state
from witful.sleeves.git import clean, destination, git, incoming
from witful.sleeves.models import Sleeve


def start(repo: Path, directory: Path, *, name: str, base: str = "main", remote: str = "origin", keys: Path | None = None) -> Sleeve:
    """
    Start from the fetched integration commit without switching the caller's checkout.

    Args:
        repo (Path): Existing private repository with no uncommitted work.
        directory (Path): New external owner-only directory for this session.
        name (str): Short non-sensitive label; a unique suffix distinguishes concurrent instances.
        base (str): Integration branch to reconcile before closure.
        remote (str): Configured private publication remote.
        keys (Path | None): Existing encryption/signing key directory for sealed collections.

    Returns:
        Sleeve: Persisted receipt after the isolated branch has been backed up remotely.

    Raises:
        SleeveError: Inputs, destination, source restoration, or publication prevents startup.
    """
    repo, directory = repo.resolve(), directory.expanduser().resolve()

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", name) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/_.-]*", base):
        raise SleeveError("Use a short lowercase sleeve label and an ordinary integration branch name.")
    git(repo, "check-ref-format", "refs/heads/" + base)
    clean(repo)
    top = Path(git(repo, "rev-parse", "--show-toplevel").stdout.strip())

    if directory.is_relative_to(top) or directory.exists():
        raise SleeveError("Choose a new sleeve directory outside the existing checkout.")
    if keys is not None and keys.expanduser().resolve().is_relative_to(directory):
        raise SleeveError("Keep key backups outside the sleeve directory.")

    with state.locked(repo):
        repository = destination(repo, remote)
        branch = f"sleeves/{name}-{uuid4().hex[:12]}"
        base_commit = incoming(repo, remote, base, branch)
        directory.mkdir(parents=True, mode=0o700)
        worktree = directory / "checkout"
        git(repo, "worktree", "add", "-b", branch, str(worktree), base_commit)
        sleeve = Sleeve(
            branch,
            base,
            remote,
            repository,
            datetime.now(UTC).isoformat(),
            base_commit,
            str(worktree),
            str(directory),
            str(keys.expanduser().resolve()) if keys else None,
        )

        # Record ownership before restoration or network I/O so an interrupted start remains discoverable.
        state.save(repo, sleeve)
        sleeve = evolve(sleeve, source_digest=sources.initialize(sleeve))
        state.save(repo, sleeve)
        git(worktree, "push", "--set-upstream", remote, f"HEAD:refs/heads/{branch}")
        return sleeve


def checkpoint(repo: Path, paths: tuple[str, ...], message: str) -> Sleeve:
    """
    Validate and sign explicitly selected changes, then back up this sleeve without updating main.

    Args:
        repo (Path): Sleeve worktree.
        paths (tuple[str, ...]): Named plaintext Git paths; empty for encrypted collection transport.
        message (str): Non-sensitive commit summary.

    Returns:
        Sleeve: Receipt updated only after the backup push succeeds.

    Raises:
        SleeveError: Closed state, merge conflicts, unsafe paths, or unrelated staging blocks publication.
    """
    with state.locked(repo):
        sleeve = state.current(repo)

        if sleeve.closed_commit is not None:
            raise SleeveError("This sleeve is closed. Start a new sleeve before further edits.")
        destination(repo, sleeve.remote, sleeve.repository)

        if git(repo, "ls-files", "--unmerged").stdout:
            raise SleeveError("Resolve the existing merge explicitly before checkpointing.")

        source_digest = sleeve.source_digest

        if sleeve.keys is not None:
            if paths:
                raise SleeveError("Encrypted checkpoints stage only the signed source transport; omit --paths.")
            paths, source_digest = sources.checkpoint(sleeve)
        elif not paths:
            raise SleeveError("Select named source paths with --paths; wholesale staging is not supported.")

        for name in paths:
            path = Path(name)

            if path.is_absolute() or not path.parts or any(part in {"..", ".git"} for part in path.parts) or name == ".":
                raise SleeveError("Checkpoint paths must name sources within the sleeve worktree.")

        staged = git(repo, "diff", "--cached", "--name-only", "-z").stdout.split("\0")

        if any(name and not any(Path(name).is_relative_to(Path(selected)) for selected in paths) for name in staged):
            raise SleeveError("The index includes unrelated paths; preserve them separately before checkpointing.")

        sources.validate(sleeve)
        git(repo, "--literal-pathspecs", "add", "--", *paths)

        if git(repo, "diff", "--cached", "--quiet", allowed=(0, 1)).returncode:
            git(repo, "-c", "commit.gpgsign=true", "commit", "-m", message)

        git(repo, "push", "--set-upstream", sleeve.remote, f"HEAD:refs/heads/{sleeve.branch}")

        if sleeve.keys is not None:
            sleeve = evolve(sleeve, source_digest=source_digest)
            state.save(repo, sleeve)

        return sleeve


def finish(repo: Path, *, pull_request: bool = False) -> Sleeve:
    """
    Reconcile current main and close only after the remote integration branch contains this history.

    Args:
        repo (Path): Clean sleeve worktree whose changes are backed up.
        pull_request (bool): Require GitHub review rather than attempting a direct fast-forward push.

    Returns:
        Sleeve: Closed receipt with the remotely observed integration revision.

    Raises:
        SleeveError: Conflicts, source validation, review, hooks, or remote movement prevents closure.
    """
    with state.locked(repo):
        sleeve = state.current(repo)
        clean(repo)
        sources.unchanged(sleeve)
        destination(repo, sleeve.remote, sleeve.repository)
        latest = incoming(repo, sleeve.remote, sleeve.base, sleeve.branch)
        head = git(repo, "rev-parse", "HEAD").stdout.strip()

        # A merge already completed on GitHub is sufficient, including recovery from an interrupted final push.
        if git(repo, "merge-base", "--is-ancestor", head, latest, allowed=(0, 1)).returncode == 0:
            sources.validate(sleeve)
            sleeve = evolve(sleeve, closed_commit=latest)
            state.save(repo, sleeve)
            return sleeve

        if sleeve.closed_commit is not None:
            raise SleeveError("A closed sleeve has diverged. Preserve its changes and start a new session.")

        # Merge into the isolated sleeve. Never reset the primary checkout, choose ours/theirs, or force-push.
        merged = git(repo, "-c", "commit.gpgsign=true", "merge", "--no-edit", latest, allowed=(0, 1))

        if merged.returncode:
            raise SleeveError("Merge blocked. Resolve conflicts in the sleeve, validate, commit, then retry finish.")

        sources.validate(sleeve)
        git(repo, "push", sleeve.remote, f"HEAD:refs/heads/{sleeve.branch}")

        if pull_request:
            urls = (
                run(
                    [
                        "gh",
                        "pr",
                        "list",
                        "--repo",
                        sleeve.repository,
                        "--head",
                        sleeve.branch,
                        "--base",
                        sleeve.base,
                        "--state",
                        "open",
                        "--json",
                        "url",
                        "--jq",
                        ".[0].url // empty",
                    ]
                )
                .decode()
                .strip()
            )

            if not urls:
                run(
                    [
                        "gh",
                        "pr",
                        "create",
                        "--repo",
                        sleeve.repository,
                        "--head",
                        sleeve.branch,
                        "--base",
                        sleeve.base,
                        "--title",
                        "Reconcile identity sleeve",
                        "--body",
                        "**What:** Reconcile an isolated identity session.\n\n**Why:** Preserve concurrent work in the shared identity."
                        "\n\n**How:** Merge the session history into the integration branch without rewriting it."
                        "\n\n**Validation:** Local source contracts passed. Required hosted checks and review remain authoritative."
                        " Use a merge commit so sleeve ancestry remains verifiable.",
                    ]
                )
            raise SleeveError("The sleeve PR awaits merge. Use a merge commit, then rerun finish; the session remains open.")

        # A concurrent writer causes a normal non-fast-forward rejection. Retrying re-fetches and reconciles it.
        git(repo, "push", sleeve.remote, f"HEAD:refs/heads/{sleeve.base}")
        observed = incoming(repo, sleeve.remote, sleeve.base, sleeve.branch)
        head = git(repo, "rev-parse", "HEAD").stdout.strip()
        git(repo, "merge-base", "--is-ancestor", head, observed)
        sleeve = evolve(sleeve, closed_commit=observed)
        state.save(repo, sleeve)
        return sleeve


def guard(repo: Path) -> None:
    """
    Fail an agent's normal shutdown gate while its sleeve remains open or contains new changes.

    Args:
        repo (Path): Sleeve worktree.

    Returns:
        None: The local receipt records a completed integration and no later changes exist.

    Raises:
        SleeveError: Finish has not verified integration or later work remains.
    """
    sleeve = state.current(repo)
    clean(repo)
    sources.unchanged(sleeve)

    if sleeve.closed_commit is None:
        raise SleeveError("Session closure is blocked: run sleeve finish and resolve any reported blocker.")
    if git(repo, "merge-base", "--is-ancestor", "HEAD", sleeve.closed_commit, allowed=(0, 1)).returncode:
        raise SleeveError("The sleeve contains commits created after closure; they must be reconciled.")


def backup(repo: Path) -> Sleeve:
    """
    Preserve already committed work even when an incomplete source edit cannot pass validation.

    Args:
        repo (Path): Existing sleeve worktree.

    Returns:
        Sleeve: Unchanged receipt; backup never marks the session closed.
    """
    with state.locked(repo):
        sleeve = state.current(repo)
        destination(repo, sleeve.remote, sleeve.repository)
        git(repo, "push", sleeve.remote, f"HEAD:refs/heads/{sleeve.branch}")
        return sleeve
