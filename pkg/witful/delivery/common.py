"""
Keep delivery subprocesses, receipts, and publication checks bounded and explicit.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from contextlib import contextmanager
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from uuid import uuid4

from .providers import backend
from .providers.base import Repository, object_value

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def run(root: Path, *args: str) -> str:
    """
    Run literal arguments without leaking provider diagnostics or changing the caller's environment.

    Args:
        root (Path): Existing working directory.
        *args (str): Executable and literal arguments, never a shell expression.

    Returns:
        str: Captured standard output.

    Raises:
        ValueError: Execution fails or exceeds fifteen minutes.
    """
    # An alternate publication index must never leak into an isolated child worktree.
    environment = dict(os.environ)
    for name in ("GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE"):
        environment.pop(name, None)
    environment["GIT_LITERAL_PATHSPECS"] = "1"
    try:
        result = subprocess.run(args, cwd=root, env=environment, text=True, capture_output=True, timeout=900, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError(f"{args[0]} did not finish; inspect the retained worktree before retrying") from None
    if result.returncode:
        raise ValueError(f"{args[0]} exited {result.returncode}; inspect the retained worktree (provider diagnostics withheld)")
    return result.stdout.rstrip("\n")


def git(root: Path, *args: str) -> str:
    """
    Invoke Git with the selected project environment.

    Args:
        root (Path): Existing checkout or worktree.
        *args (str): Literal Git arguments.

    Returns:
        str: Captured output.
    """
    return run(root, "git", *args)


def commit(root: Path, revision: str) -> str:
    """
    Resolve a revision before switching worktrees, preventing context-dependent HEAD errors.

    Args:
        root (Path): Source repository.
        revision (str): Revision to resolve, never an option.

    Returns:
        str: Immutable full commit identifier.
    """
    return git(root, "rev-parse", "--verify", "--end-of-options", revision + "^{commit}")


def branch_name(root: Path, name: str) -> str:
    """
    Validate one explicit branch ref before constructing Git arguments.

    Args:
        root (Path): Existing repository.
        name (str): Untrusted branch name.

    Returns:
        str: Validated name.

    Raises:
        ValueError: The name cannot identify a branch safely.
    """
    if name.startswith("-") or name == "HEAD":
        raise ValueError("Select a named branch")
    git(root, "check-ref-format", "refs/heads/" + name)
    return name


def destination(root: Path, selector: str = "origin") -> Repository:
    """
    Bind one credential-free fetch/push remote to an explicit API provider.

    Args:
        root (Path): Existing repository.
        selector (str): Remote name, or github:REMOTE / gitlab:REMOTE for explicit host selection.

    Returns:
        Repository: Provider, host, namespace and transport binding.

    Raises:
        ValueError: Remote is missing, ambiguous, credential-bearing, or unsupported.
    """
    provider, separator, remote = selector.partition(":")
    if not separator:
        remote, provider = provider, ""
    if not re.fullmatch(r"[A-Za-z0-9_][\w.-]*", remote) or provider not in ("", "github", "gitlab"):
        raise ValueError("Select a remote, optionally qualified as github:REMOTE or gitlab:REMOTE")
    fetch = git(root, "remote", "get-url", "--all", remote)
    push = git(root, "remote", "get-url", "--push", "--all", remote)
    if fetch != push or any(character in fetch for character in "\n\r\t"):
        raise ValueError("Expected one matching credential-free fetch/push URL")
    # Normalize SSH transport for parsing; preserve the exact original URL in the receipt.
    normalized = re.sub(r"^git@([^/:]+):", r"ssh://git@\1/", fetch)
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in ("https", "ssh")
        or not parsed.hostname
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (parsed.scheme == "https" and parsed.username is not None)
        or (parsed.scheme == "ssh" and parsed.username not in (None, "git"))
        or (parsed.scheme == "ssh" and parsed.port is not None)
    ):
        raise ValueError("Use a credential-free HTTPS or standard SSH Git remote")
    host = parsed.netloc if parsed.scheme == "https" else parsed.hostname
    project = parsed.path.removeprefix("/").removesuffix(".git")
    parts = project.split("/")
    if len(parts) < 2 or any(not re.fullmatch(r"[\w.-]+", part) or part in (".", "..") for part in parts):
        raise ValueError("Expected a namespaced Git project")
    known_provider = {"github.com": "github", "gitlab.com": "gitlab"}.get(host, "")
    if provider and known_provider and provider != known_provider:
        raise ValueError("Provider does not match the selected hosted domain")
    provider = provider or known_provider
    if not provider or (provider == "github" and len(parts) != 2):
        raise ValueError("Self-managed hosts require an explicit provider and supported project path")
    return Repository(provider, host, project, remote, fetch)


def saved_destination(root: Path, value: object) -> Repository:
    """
    Revalidate the complete receipt binding against current Git configuration.

    Args:
        root (Path): Source or candidate worktree.
        value (object): Stored repository binding.

    Returns:
        Repository: Matching current destination.

    Raises:
        ValueError: The receipt is legacy, malformed, or any destination field changed.
    """
    if not isinstance(value, dict):
        raise ValueError("Legacy receipt lacks a provider binding; prepare a new reviewed receipt")
    data = object_value(value)
    repository = destination(root, text(data["provider"]) + ":" + text(data["remote"]))
    if repository.data() != data:
        raise ValueError("Delivery destination changed since preparation")
    return repository


def remote_head(root: Path, branch: str, remote: str = "origin") -> str:
    """
    Observe the actual remote ref instead of a potentially stale tracking branch.

    Args:
        root (Path): Existing checkout.
        branch (str): Validated branch name.
        remote (str): Validated selected remote.

    Returns:
        str: Remote object identifier, or empty when the branch does not exist.
    """
    rows = git(root, "ls-remote", "--refs", remote, "refs/heads/" + branch).splitlines()
    return rows[0].split()[0] if rows else ""


def signing(root: Path) -> None:
    """
    Require the configured owner and signing identity before creating commits.

    Args:
        root (Path): Repository whose effective settings apply.

    Returns:
        None: Author, committer, and mandatory signing settings are present.

    Raises:
        ValueError: Signing is disabled or no signing key is configured.
    """
    git(root, "var", "GIT_AUTHOR_IDENT")
    git(root, "var", "GIT_COMMITTER_IDENT")
    for name in ("commit.gpgsign", "tag.gpgsign"):
        if git(root, "config", "--bool", "--get", name) != "true":
            raise ValueError(f"Enable {name} using the intended registered owner key")
    if not git(root, "config", "--get", "user.signingkey"):
        raise ValueError("Configure the intended signing key")


def checks(root: Path, commands: list[list[str]]) -> None:
    """
    Require caller-selected semantic checks followed by all configured hooks.

    Args:
        root (Path): Isolated candidate worktree.
        commands (list[list[str]]): Reviewed executable argument arrays, not shell strings.

    Returns:
        None: Checks passed without changing tracked or untracked source.

    Raises:
        ValueError: Checks were omitted, failed, or changed the candidate.
    """
    if not commands:
        raise ValueError("Supply at least one relevant validation command")
    for command in commands:
        run(root, *command)
    if (root / ".pre-commit-config.yaml").is_file():
        run(root, "pre-commit", "run", "--all-files")
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Checks changed the candidate; review and commit those changes before continuing")


def publish(root: Path, repository: Repository, branch: str, expected: str, head: str) -> None:
    """
    Publish one signed revision with an exact lease, then verify remote identity and provider signing.

    Args:
        root (Path): Candidate worktree.
        repository (Repository): Previously bound provider and Git destination.
        branch (str): Explicit destination branch.
        expected (str): Observed original head; empty means the branch must be absent.
        head (str): Signed candidate commit.

    Returns:
        None: The remote ref and provider signature match the candidate.

    Raises:
        ValueError: Origin changed, another writer advanced the ref, or verification failed.
    """
    if destination(root, repository.provider + ":" + repository.remote) != repository:
        raise ValueError("Origin changed since preparation")
    git(root, "verify-commit", head)
    current = remote_head(root, branch, repository.remote)
    if current not in (expected, head):
        raise ValueError("Remote head changed; refresh and reassess instead of overwriting it")
    # A lost response can follow a successful push. Readback makes that retry idempotent.
    if current != head:
        git(
            root,
            "push",
            "--no-follow-tags",
            f"--force-with-lease=refs/heads/{branch}:{expected}",
            repository.remote,
            f"{head}:refs/heads/{branch}",
        )
    if remote_head(root, branch, repository.remote) != head:
        raise ValueError("Remote readback did not match the candidate")
    with backend(repository) as provider:
        if not provider.verified(head):
            raise ValueError("Ref was pushed, but the provider has not verified its signature; receipt remains pending")


def save(path: Path, values: dict[str, object], *, create: bool = False) -> None:
    """
    Atomically persist private receipts without replacing an existing initial plan.

    Args:
        path (Path): Caller-selected receipt outside the candidate worktree.
        values (dict[str, object]): Redacted state without source contents or credentials.
        create (bool): Require a new receipt path.

    Returns:
        None: Owner-readable receipt is durable on the local filesystem.
    """
    payload = (json.dumps(values, indent=2, sort_keys=True) + "\n").encode()
    temporary = path.with_name(path.name + "." + uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            os.chmod(temporary, 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if create:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read(path: Path) -> dict[str, object]:
    """
    Read a structured local plan or receipt without executing its contents.

    Args:
        path (Path): Existing JSON file.

    Returns:
        dict[str, object]: Decoded object.

    Raises:
        ValueError: The document is not an object.
    """
    value: object = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return {str(key): item for key, item in value.items()}


def text(value: object) -> str:
    """
    Validate a string at the input boundary.

    Args:
        value (object): Decoded field.

    Returns:
        str: Validated string.

    Raises:
        ValueError: The field has another type.
    """
    if not isinstance(value, str):
        raise ValueError("Expected a string field")
    return value


def arrays(value: object) -> list[list[str]]:
    """
    Validate a nonempty list of nonempty string arrays.

    Args:
        value (object): Decoded batches or command vectors.

    Returns:
        list[list[str]]: Validated arrays.

    Raises:
        ValueError: The field is empty or malformed.
    """
    if not isinstance(value, list) or not value:
        raise ValueError("Expected nonempty arrays")
    result: list[list[str]] = []
    for row in value:
        if not isinstance(row, list) or not row:
            raise ValueError("Expected nonempty string arrays")
        result.append([text(item) for item in row])
    return result


@contextmanager
def exclusive(receipt: Path) -> Iterator[None]:
    """
    Reject concurrent writers to one receipt; never infer that a stale lock grants ownership.

    Args:
        receipt (Path): Local operation receipt.

    Yields:
        None: Exclusive local ownership for this invocation.
    """
    lock = receipt.with_name(receipt.name + ".lock")
    with lock.open("x") as stream:
        stream.write(str(os.getpid()))
    try:
        yield
    finally:
        lock.unlink()
