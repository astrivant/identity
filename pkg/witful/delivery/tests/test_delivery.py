"""
Exercise delivery with real signed Git histories and synthetic host responses.
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from witful.delivery import common, prs, recovery
from witful.delivery.cli import main
from witful.delivery.providers.base import Backend, Repository, bounded

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest import CaptureFixture, FixtureRequest, MonkeyPatch


@pytest.fixture(params=["github", "gitlab"])
def repository(tmp_path: Path, monkeypatch: MonkeyPatch, request: FixtureRequest) -> Path:
    """
    Isolate Git configuration and create an SSH-signed local repository with a bare remote.

    Args:
        tmp_path (Path): Temporary fixture directory.
        monkeypatch (MonkeyPatch): Replace only host evidence and ambient Git configuration.
        request (FixtureRequest): Hosting provider whose shared Git lifecycle is exercised.

    Returns:
        Path: Real source checkout with a published signed baseline.
    """
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for variable in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(variable, raising=False)
    root, remote, key = tmp_path / "source", tmp_path / "remote.git", tmp_path / "signer"
    common.run(tmp_path, "git", "init", "--bare", str(remote))
    common.run(tmp_path, "git", "init", "-b", "main", str(root))
    common.run(tmp_path, "ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key))
    allowed = tmp_path / "allowed-signers"
    allowed.write_text("fixture@example.invalid " + key.with_suffix(".pub").read_text())
    for name, value in {
        "user.name": "Fixture",
        "user.email": "fixture@example.invalid",
        "gpg.format": "ssh",
        "user.signingkey": str(key),
        "gpg.ssh.allowedSignersFile": str(allowed),
        "commit.gpgsign": "true",
        "tag.gpgsign": "true",
        "core.hooksPath": str(tmp_path / "no-hooks"),
    }.items():
        common.git(root, "config", name, value)
    write_commit(root, "base.txt", "baseline\n")
    common.git(root, "remote", "add", "origin", str(remote))
    common.git(root, "push", "origin", "main")
    binding = Repository(str(request.param), str(request.param) + ".com", "example/project", "origin", str(remote))
    for module in (common, prs, recovery):
        monkeypatch.setattr(module, "destination", lambda root, selector="origin": binding)
    monkeypatch.setattr(common, "backend", fake_backend)
    monkeypatch.setattr(prs, "backend", fake_backend)
    return root


class FixtureBackend:
    """
    Supply provider evidence while fixture Git operations remain real.
    """

    def requests(self) -> list[dict[str, object]]:
        """
        Return an empty default inventory.

        Returns:
            list[dict[str, object]]: Tests inject request metadata separately.
        """
        return []

    def default_branch(self) -> str:
        """
        Preserve the fixture integration branch.

        Returns:
            str: Default branch name.
        """
        return "main"

    def verified(self, revision: str) -> bool:
        """
        Acknowledge a remotely read-back fixture signature.

        Args:
            revision (str): Candidate commit already verified locally by real Git.

        Returns:
            bool: Synthetic host signature evidence.
        """
        return True


@contextmanager
def fake_backend(repository: Repository) -> Iterator[Backend]:
    """
    Isolate provider calls from the real local Git fixture.

    Args:
        repository (Repository): Selected destination.

    Yields:
        Backend: Fixture evidence only.
    """
    yield FixtureBackend()


def write_commit(root: Path, path: str, content: str) -> str:
    """
    Append a signed fixture change.

    Args:
        root (Path): Fixture checkout.
        path (str): Relative file name.
        content (str): Synthetic content.

    Returns:
        str: New commit identifier.
    """
    (root / path).write_text(content)
    common.git(root, "add", "--", path)
    common.git(root, "commit", "-S", "-m", "Fixture change")
    return common.commit(root, "HEAD")


def row(identifier: int, branch: str, base: str, head: str = "", lines: int = 1) -> dict[str, object]:
    """
    Construct synthetic PR metadata.

    Args:
        identifier (int): PR number.
        branch (str): Head branch.
        base (str): Declared base branch.
        head (str): Immutable head when Git operations use it.
        lines (int): Added-line count.

    Returns:
        dict[str, object]: Minimal supported PR row.
    """
    return {
        "number": identifier,
        "title": "Fixture",
        "url": f"https://github.com/example/project/pull/{identifier}",
        "headRefName": branch,
        "baseRefName": base,
        "headRefOid": head,
        "isCrossRepository": False,
        "additions": lines,
        "deletions": 0,
        "changedFiles": 1,
        "isDraft": False,
        "reviewDecision": "",
    }


def test_review_order_preserves_dependencies_and_uses_stable_ties() -> None:
    """
    Put prerequisites before smaller children without changing input metadata.

    Returns:
        None: Inferred and declared dependencies dominate size and number tie-breaks.
    """
    rows = [row(6, "child", "parent"), row(5, "parent", "main", lines=20), row(12, "small", "main")]
    original = json.dumps(rows)
    assert [item["number"] for item in prs.ordered(rows, {})] == [12, 5, 6]
    assert [item["number"] for item in prs.ordered(rows, {"12": [6]})] == [5, 6, 12]
    assert json.dumps(rows) == original
    with pytest.raises(ValueError, match="cycle"):
        prs.ordered(rows, {"5": [6]})
    with pytest.raises(ValueError, match="not in"):
        prs.ordered(rows, {"5": [99]})
    with pytest.raises(ValueError, match="Duplicate"):
        prs.ordered([rows[0], rows[0]], {})


def test_stack_rebase_uses_original_parent_sha(repository: Path, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Rebase a real parent and child without replaying the old parent or losing either feature.

    Args:
        repository (Path): Signed Git fixture.
        tmp_path (Path): Receipt/worktree container.
        monkeypatch (MonkeyPatch): Supply current synthetic PR metadata.

    Returns:
        None: Both remote branches are signed and ordered atop the updated main; caller staging survives.
    """
    base = common.commit(repository, "HEAD")
    common.git(repository, "switch", "-c", "parent")
    parent = write_commit(repository, "parent.txt", "parent\n")
    common.git(repository, "push", "origin", "parent")
    common.git(repository, "switch", "-c", "child")
    child = write_commit(repository, "child.txt", "child\n")
    common.git(repository, "push", "origin", "child")
    common.git(repository, "switch", "main")
    new_base = write_commit(repository, "new-base.txt", "current base\n")
    common.git(repository, "push", "origin", "main")
    (repository / "unrelated.txt").write_text("keep staged\n")
    common.git(repository, "add", "unrelated.txt")
    staged = common.git(repository, "diff", "--cached")
    rows = [row(5, "parent", "main", parent), row(6, "child", "parent", child)]
    monkeypatch.setattr(prs, "inventory", lambda root, dependencies, remotes=("origin",): rows)
    first, second = tmp_path / "parent.json", tmp_path / "child.json"
    parent_state = prs.prepare(repository, 5, base, tmp_path / "parent-work", first)
    parent_head = common.text(parent_state["head"])
    prs.publish_pr(first, parent_head, [[sys.executable, "-c", "assert open('parent.txt').read() == 'parent\\n'"]])
    child_state = prs.prepare(repository, 6, parent, tmp_path / "child-work", second)
    assert child_state["base"] == parent_head
    child_head = common.text(child_state["head"])
    child_root = Path(common.text(child_state["worktree"]))
    assert common.git(child_root, "rev-list", "--count", parent_head + ".." + child_head) == "1"
    common.git(child_root, "merge-base", "--is-ancestor", new_base, child_head)
    prs.publish_pr(second, child_head, [[sys.executable, "-c", "assert open('child.txt').read() == 'child\\n'"]])
    assert common.remote_head(repository, "child") == child_head
    assert common.git(repository, "diff", "--cached") == staged
    assert common.commit(repository, "HEAD") == new_base


def test_conflict_preserves_receipt_and_original_remote(repository: Path, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Keep meaningful conflicts available for deliberate resolution without publishing a partial rebase.

    Args:
        repository (Path): Signed fixture.
        tmp_path (Path): Worktree and receipt paths.
        monkeypatch (MonkeyPatch): Supply feature PR metadata.

    Returns:
        None: The original remote and a recoverable conflicted worktree remain intact.
    """
    base = common.commit(repository, "HEAD")
    common.git(repository, "switch", "-c", "feature")
    feature = write_commit(repository, "base.txt", "feature policy\n")
    common.git(repository, "push", "origin", "feature")
    common.git(repository, "switch", "main")
    write_commit(repository, "base.txt", "main policy\n")
    common.git(repository, "push", "origin", "main")
    monkeypatch.setattr(prs, "inventory", lambda root, dependencies, remotes=("origin",): [row(1, "feature", "main", feature)])
    receipt, worktree = tmp_path / "conflict.json", tmp_path / "conflict"
    with pytest.raises(ValueError, match="git exited"):
        prs.prepare(repository, 1, base, worktree, receipt)
    assert common.read(receipt)["original"] == feature
    assert common.git(worktree, "ls-files", "--unmerged")
    assert common.remote_head(repository, "feature") == feature
    with pytest.raises(ValueError, match="Finish"):
        prs.publish_pr(receipt, common.commit(worktree, "HEAD"), [[sys.executable, "-V"]])


def recovery_plan(repository: Path, tmp_path: Path) -> Path:
    """
    Commit an unsent large blob and plan smaller independent files before it.

    Args:
        repository (Path): Source checkout.
        tmp_path (Path): Plan paths.

    Returns:
        Path: New recovery receipt with a deliberate omitted file.
    """
    write_commit(repository, "large.bin", "x" * 100000)
    write_commit(repository, "small.txt", "metadata\n")
    source = write_commit(repository, "omitted.txt", "not selected\n")
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps({"source": source, "base_branch": "main", "branch": "recovery/fixture", "batches": [["large.bin"], ["small.txt"]]})
    )
    receipt = tmp_path / "receipt.json"
    recovery.plan(repository, spec, tmp_path / "recovery-work", receipt)
    return receipt


@pytest.mark.parametrize("lost_response", [False, True])
def test_partial_push_and_resume_keep_small_metadata(
    repository: Path, tmp_path: Path, monkeypatch: MonkeyPatch, lost_response: bool
) -> None:
    """
    Resume after a failed large push or lost acknowledgement without resending an accepted commit.

    Args:
        repository (Path): Signed Git fixture.
        tmp_path (Path): Plan storage.
        monkeypatch (MonkeyPatch): Inject one transport interruption.
        lost_response (bool): Fail after acceptance instead of before transfer.

    Returns:
        None: The small checkpoint survives and the final branch contains exactly two recovery commits.
    """
    receipt = recovery_plan(repository, tmp_path)
    original_head = common.commit(repository, "HEAD")
    state = common.read(receipt)
    assert state["batches"] == [["small.txt"], ["large.bin"]]
    real_git, pushed = common.git, []

    def interrupt(root: Path, *args: str) -> str:
        """
        Interrupt the second actual push once, preserving remote acceptance when requested.

        Args:
            root (Path): Candidate checkout.
            *args (str): Git arguments.

        Returns:
            str: Real Git output.
        """
        if args[0] == "push":
            pushed.append(args[-1])
            if len(pushed) == 2:
                if lost_response:
                    real_git(root, *args)
                raise ValueError("simulated transfer interruption")
        return real_git(root, *args)

    monkeypatch.setattr(common, "git", interrupt)
    commands = [[sys.executable, "-c", "assert open('small.txt').read() == 'metadata\\n'"]]
    with pytest.raises(ValueError, match="simulated"):
        recovery.apply(receipt, commands)
    partial = common.read(receipt)
    assert isinstance(partial["completed"], list)
    assert len(partial["completed"]) == 1
    accepted = common.remote_head(repository, "recovery/fixture")
    if not lost_response:
        assert common.git(repository, "ls-tree", "-r", "--name-only", accepted) == "base.txt\nsmall.txt"
    result = recovery.apply(receipt, commands)
    assert result["status"] == "selected-batches-published"
    assert result["omitted"] == ["omitted.txt"]
    assert len(pushed) == (2 if lost_response else 3)
    final = common.remote_head(repository, "recovery/fixture")
    assert common.git(repository, "rev-list", "--count", common.text(state["base"]) + ".." + final) == "2"
    assert common.git(repository, "show", final + ":large.bin") == "x" * 100000
    assert common.commit(repository, "HEAD") == original_head
    assert recovery.apply(receipt, commands)["completed"] == result["completed"]


def test_changed_remote_and_failed_checks_block_publication(repository: Path, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Reject failing semantic checks and a competing writer without overwriting either history.

    Args:
        repository (Path): Signed Git fixture.
        tmp_path (Path): Plan files.
        monkeypatch (MonkeyPatch): Isolate an alternate parent publication index.

    Returns:
        None: Checks and explicit remote leases remain mandatory.
    """
    receipt = recovery_plan(repository, tmp_path)
    # The source caller may be using an alternate index; children must use their own indexes.
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "caller.index"))
    with pytest.raises(ValueError, match="exited"):
        recovery.apply(receipt, [[sys.executable, "-c", "raise SystemExit(1)"]])
    assert common.remote_head(repository, "recovery/fixture") == ""
    assert not (tmp_path / "caller.index").exists()
    head = common.commit(repository, "HEAD")
    common.git(repository, "push", "origin", head + ":refs/heads/recovery/fixture")
    with pytest.raises(ValueError, match="changed"):
        recovery.apply(receipt, [[sys.executable, "-V"]])
    assert common.remote_head(repository, "recovery/fixture") == head


@pytest.mark.parametrize("paths", [[["../outside"]], [["base.txt"], ["base.txt"]], [["."]], [[".git/config"]], [["missing"]]])
def test_recovery_rejects_ambiguous_paths(repository: Path, paths: list[list[str]]) -> None:
    """
    Reject unsafe or unsupported selectors before creating a worktree.

    Args:
        repository (Path): Synthetic checkout.
        paths (list[list[str]]): Invalid selections.

    Returns:
        None: Path parsing fails closed.
    """
    with pytest.raises(ValueError):
        recovery.batches(repository, common.commit(repository, "HEAD"), paths)


def test_cli_catalog_and_receipt_exclusion(tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]) -> None:
    """
    Produce clickable order and reject concurrent receipt use without overwriting an existing plan.

    Args:
        tmp_path (Path): Receipt directory.
        monkeypatch (MonkeyPatch): Supply offline PR metadata.
        capsys (CaptureFixture[str]): Captured command output.

    Returns:
        None: Read-only output and exclusive local state contracts hold.
    """
    monkeypatch.setattr(prs, "inventory", lambda root, dependencies, remotes=("origin",): [row(5, "feature", "main")])
    assert main(["pr", "show"]) == 0
    assert "[#5 Fixture](https://github.com/example/project/pull/5)" in capsys.readouterr().out
    receipt = tmp_path / "receipt.json"
    common.save(receipt, {"kind": "fixture"}, create=True)
    with pytest.raises(FileExistsError):
        common.save(receipt, {"kind": "replacement"}, create=True)
    assert common.read(receipt)["kind"] == "fixture"
    with common.exclusive(receipt), pytest.raises(FileExistsError), common.exclusive(receipt):
        pytest.fail("Concurrent execution must never obtain the lock")


def test_completed_receipt_requires_fresh_remote_evidence(repository: Path, tmp_path: Path) -> None:
    """
    Treat completed receipts as historical evidence when the remote branch changes later.

    Args:
        repository (Path): Signed Git fixture.
        tmp_path (Path): Recovery plan directory.

    Returns:
        None: A deleted published ref cannot be reported as currently delivered.
    """
    receipt = recovery_plan(repository, tmp_path)
    recovery.apply(receipt, [[sys.executable, "-V"]])
    common.git(repository, "push", "origin", ":refs/heads/recovery/fixture")
    with pytest.raises(ValueError, match="historical"):
        recovery.apply(receipt, [[sys.executable, "-V"]])


def test_literal_names_and_coherent_batches(repository: Path) -> None:
    """
    Preserve literal path semantics and keep dependent files together while ordering total bytes.

    Args:
        repository (Path): Synthetic checkout.

    Returns:
        None: Git pathspec metacharacters are literal and groups sort by aggregate source bytes.
    """
    write_commit(repository, "[a].txt", "123")
    source = write_commit(repository, "medium.txt", "12345")
    assert recovery.batches(repository, source, [["base.txt"], ["[a].txt", "medium.txt"]]) == [["[a].txt", "medium.txt"], ["base.txt"]]
    (repository / "link.txt").symlink_to("base.txt")
    common.git(repository, "add", "link.txt")
    common.git(repository, "commit", "-S", "-m", "Fixture symbolic link")
    with pytest.raises(ValueError, match="regular"):
        recovery.batches(repository, common.commit(repository, "HEAD"), [["link.txt"]])


def test_all_hooks_follow_semantic_checks(repository: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Run configured all-file hooks and reject any resulting source drift.

    Args:
        repository (Path): Fixture checkout.
        monkeypatch (MonkeyPatch): Record checks without installing arbitrary hooks.

    Returns:
        None: A changed candidate never passes the publication gate.
    """
    write_commit(repository, ".pre-commit-config.yaml", "repos: []\n")
    observed: list[tuple[str, ...]] = []

    def record(root: Path, *args: str) -> str:
        """
        Record only validation commands without replacing Git's source-state checks.

        Args:
            root (Path): Candidate directory.
            *args (str): Requested command.

        Returns:
            str: Empty successful output.
        """
        observed.append(args)
        return ""

    original_git = common.git
    monkeypatch.setattr(common, "run", record)
    monkeypatch.setattr(common, "git", lambda root, *args: "")
    common.checks(repository, [["pytest", "tests"]])
    assert observed == [("pytest", "tests"), ("pre-commit", "run", "--all-files")]
    monkeypatch.setattr(common, "git", lambda root, *args: " M tracked.txt")
    with pytest.raises(ValueError, match="changed"):
        common.checks(repository, [["pytest", "tests"]])
    monkeypatch.setattr(common, "git", original_git)


def test_inventory_rejects_truncation_and_preserves_metadata(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Fail closed at the inventory cap instead of silently omitting PR dependencies.

    Args:
        tmp_path (Path): Existing working directory.
        monkeypatch (MonkeyPatch): Provide controlled backend inventory responses.

    Returns:
        None: Complete inventories retain review context; capped inventories fail.
    """
    metadata = row(5, "feature", "main")
    metadata["body"] = "Reviewed dependency intent"
    monkeypatch.setattr(prs, "destination", lambda root, remote: Repository("github", "github.com", "example/project"))
    monkeypatch.setattr(prs, "backend", fake_backend)
    monkeypatch.setattr(FixtureBackend, "requests", lambda self: [metadata])
    assert prs.inventory(tmp_path, {})[0]["body"] == "Reviewed dependency intent"
    with pytest.raises(ValueError, match="Capped"):
        bounded([metadata] * 1000)


def test_rebase_and_publication_use_selected_named_remote(repository: Path, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Exercise a GitLab mirror without relying on any origin remote during mutation.

    Args:
        repository (Path): Real signed Git fixture.
        tmp_path (Path): Private receipt and candidate paths.
        monkeypatch (MonkeyPatch): Supply host metadata for the named mirror.

    Returns:
        None: The selected mirror receives the signed candidate and signature failures retain pending state.
    """
    base = common.commit(repository, "HEAD")
    common.git(repository, "switch", "-c", "feature")
    head = write_commit(repository, "feature.txt", "reviewed\n")
    common.git(repository, "push", "origin", "feature")
    url = common.git(repository, "remote", "get-url", "origin")
    common.git(repository, "remote", "rename", "origin", "mirror")
    binding = Repository("gitlab", "gitlab.com", "group/project", "mirror", url)
    for module in (common, prs, recovery):
        monkeypatch.setattr(module, "destination", lambda root, selector="origin": binding)
    monkeypatch.setattr(prs, "inventory", lambda root, dependencies, remotes: [row(5, "feature", "main", head)])
    receipt = tmp_path / "mirror.json"
    state = prs.prepare(repository, 5, base, tmp_path / "mirror-work", receipt, "gitlab:mirror")
    monkeypatch.setattr(FixtureBackend, "verified", lambda self, revision: False)
    with pytest.raises(ValueError, match="signature"):
        prs.publish_pr(receipt, common.text(state["head"]), [[sys.executable, "-V"]])
    assert common.read(receipt)["status"] == "review"
    monkeypatch.setattr(FixtureBackend, "verified", lambda self, revision: True)
    assert prs.publish_pr(receipt, head, [[sys.executable, "-V"]])["status"] == "published"
    assert common.remote_head(repository, "feature", "mirror") == head
