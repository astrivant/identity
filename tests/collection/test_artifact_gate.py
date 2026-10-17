"""
Exercise publication boundaries with immutable Git snapshots and real signed encryption.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml
from attrs import evolve
from cryptography.exceptions import InvalidTag
from witful.collection import material
from witful.collection.cli import main
from witful.collection.crypto import encrypt, save
from witful.collection.gate.check import Checker
from witful.collection.gate.cli import push_ranges
from witful.collection.gate.git import commit, git, history, snapshot
from witful.collection.keys import prepare, signing_environment
from witful.collection.managed import PUBLIC, seal_file
from witful.collection.models import CONFIG, SOURCE, load_config
from witful.exceptions import ArtifactGateError
from witful.knowledge.contracts import as_data

if TYPE_CHECKING:
    from pytest import CaptureFixture, MonkeyPatch, TempPathFactory


@pytest.fixture(scope="module")
def keys(tmp_path_factory: TempPathFactory) -> Path:
    """
    Create test-only signing and encryption material outside every Git fixture.

    Args:
        tmp_path_factory (TempPathFactory): Isolated test storage.

    Returns:
        Path: Existing complete synthetic backup.
    """
    directory = tmp_path_factory.mktemp("artifact-keys") / "keys"
    prepare(directory, "example/collection")
    return directory


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """
    Initialize a synthetic repository without global signing or hook side effects.

    Args:
        tmp_path (Path): Test-owned parent directory.

    Returns:
        Path: Clean initial commit with public source only.
    """
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "--initial-branch=main")
    for name, value in (
        ("user.name", "Synthetic Test"),
        ("user.email", "test@example.invalid"),
        ("commit.gpgsign", "false"),
        ("tag.gpgsign", "false"),
        ("core.hooksPath", str(tmp_path / "no-hooks")),
    ):
        git(root, "config", name, value)
    (root / "README.md").write_text("Public documentation\n")
    git(root, "add", "README.md")
    git(root, "commit", "-m", "Public baseline")
    return root


@pytest.fixture
def encrypted(repository: Path, keys: Path, monkeypatch: MonkeyPatch) -> Path:
    """
    Stage one real encrypted generation; isolate only separately tested host attestation.

    Args:
        repository (Path): Synthetic Git checkout.
        keys (Path): Independent test backup.
        monkeypatch (MonkeyPatch): Host storage metadata boundary.

    Returns:
        Path: Complete staged ciphertext and verification metadata.
    """
    monkeypatch.setattr(material, "require_protected", lambda path: None)
    config = prepare(keys, "example/collection")
    (repository / CONFIG).parent.mkdir()
    (repository / CONFIG).write_text(json.dumps(as_data(config)))
    save(
        repository,
        SOURCE,
        encrypt(b"SYNTHETIC_PRIVATE_DATA", (keys / "collection.pub").read_bytes(), config, "sources"),
        (keys / "cosign.pub").read_bytes(),
        config,
        signing_environment(keys),
    )
    (repository / PUBLIC).write_bytes((keys / "cosign.pub").read_bytes())
    git(repository, "add", CONFIG, "collection")
    return repository


def test_public_source_requires_no_keys(repository: Path) -> None:
    """
    Keep public source and nested synthetic fixtures outside private collection namespaces.

    Args:
        repository (Path): Synthetic public checkout.

    Returns:
        None: Public source passes without opening keys or invoking cryptographic tooling.
    """
    path = repository / "tests/fixtures/lessons.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("synthetic fixture")
    git(repository, "add", "tests")
    assert Checker([]).check(snapshot(repository)) == 0
    assert main(["check-artifacts", "--checkout", str(repository), "--revision", "HEAD"]) == 0


@pytest.mark.parametrize("name", ["lessons.jsonl", "instructions.md", "knowledge/catalog.json", ".witful/cache.json"])
def test_plaintext_staged_but_deleted_locally_fails(repository: Path, name: str) -> None:
    """
    Refuse staged private records even when their working files have been removed.

    Args:
        repository (Path): Synthetic public checkout.
        name (str): Private collection path.

    Returns:
        None: Index content, rather than working-tree appearance, controls publication.
    """
    path = repository / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("SYNTHETIC_PRIVATE_DATA")
    git(repository, "add", name)
    path.unlink()
    with pytest.raises(ArtifactGateError, match="plaintext"):
        Checker([]).check(snapshot(repository))


def test_staged_encryption_ignores_unstaged_plaintext(encrypted: Path, keys: Path) -> None:
    """
    Authenticate actual staged bytes, including sidecars, without touching working files.

    Args:
        encrypted (Path): Valid staged generation.
        keys (Path): Independent verification backup.

    Returns:
        None: An unrelated working replacement neither hides nor invalidates the indexed artifact.
    """
    (encrypted / SOURCE).write_text("UNSTAGED_PRIVATE_DATA")
    checker = Checker([keys])
    assert checker.check(snapshot(encrypted)) == 1
    assert checker.check(snapshot(encrypted)) == 1
    assert (encrypted / SOURCE).read_text() == "UNSTAGED_PRIVATE_DATA"


def test_plaintext_envelope_fails_despite_valid_working_copy(encrypted: Path, keys: Path) -> None:
    """
    Prevent a valid unstaged ciphertext from disguising a plaintext publication candidate.

    Args:
        encrypted (Path): Valid staged generation.
        keys (Path): Independent verification backup.

    Returns:
        None: Structurally invalid staged encryption fails closed.
    """
    original = (encrypted / SOURCE).read_bytes()
    (encrypted / SOURCE).write_text("SYNTHETIC_PRIVATE_DATA")
    git(encrypted, "add", SOURCE)
    (encrypted / SOURCE).write_bytes(original)
    with pytest.raises(ValueError):
        Checker([keys]).check(snapshot(encrypted))


def test_missing_keys_explains_recovery_without_echoing_data(encrypted: Path, capsys: CaptureFixture[str]) -> None:
    """
    Give actionable key-location guidance without revealing source or provider diagnostics.

    Args:
        encrypted (Path): Staged encrypted generation without a selected key directory.
        capsys (CaptureFixture[str]): CLI output capture.

    Returns:
        None: A missing backup blocks the command with status two and safe guidance.
    """
    with pytest.raises(SystemExit) as failure:
        main(["check-artifacts", "--checkout", str(encrypted), "--staged"])
    assert failure.value.code == 2
    error = capsys.readouterr().err
    assert "--key-dir" in error
    assert "SYNTHETIC_PRIVATE_DATA" not in error


@pytest.mark.parametrize("suffix", [".sha256", ".sigstore.json"])
def test_invalid_sidecars_fail(encrypted: Path, keys: Path, suffix: str) -> None:
    """
    Reject changed verification metadata in the same index as the ciphertext.

    Args:
        encrypted (Path): Staged encrypted generation.
        keys (Path): Independent trusted backup.
        suffix (str): Verification sidecar to corrupt.

    Returns:
        None: Both checksum and signature validation remain required.
    """
    (encrypted / (SOURCE + suffix)).write_text("invalid")
    git(encrypted, "add", SOURCE + suffix)
    with pytest.raises(ValueError):
        Checker([keys]).check(snapshot(encrypted))


def test_signed_but_unauthentic_ciphertext_fails(encrypted: Path, keys: Path) -> None:
    """
    Prove that a valid signature and envelope shape alone do not establish encryption.

    Args:
        encrypted (Path): Staged encrypted generation.
        keys (Path): Independent trusted backup.

    Returns:
        None: Authenticated decryption detects a modified ciphertext even after re-signing it.
    """
    config = load_config(encrypted)
    value = json.loads((encrypted / SOURCE).read_bytes())
    data = bytearray(base64.b64decode(value["ciphertext"]))
    data[-1] ^= 1
    value["ciphertext"] = base64.b64encode(data).decode()
    save(encrypted, SOURCE, json.dumps(value).encode(), (keys / "cosign.pub").read_bytes(), config, signing_environment(keys))
    git(encrypted, "add", "collection")
    with pytest.raises(InvalidTag):
        Checker([keys]).check(snapshot(encrypted))


@pytest.mark.parametrize("relative", [CONFIG, PUBLIC, SOURCE, SOURCE + ".sha256"])
def test_missing_inventory_members_fail(encrypted: Path, keys: Path, relative: str) -> None:
    """
    Require policy, ciphertext and verification metadata in the same publication snapshot.

    Args:
        encrypted (Path): Complete staged generation.
        keys (Path): Trusted backup.
        relative (str): Owned file omitted from the index.

    Returns:
        None: Missing configuration cannot silently disable the encrypted-artifact gate.
    """
    git(encrypted, "rm", "--cached", "--", relative)
    with pytest.raises(ArtifactGateError):
        Checker([keys]).check(snapshot(encrypted))


def test_managed_file_is_also_authenticated(encrypted: Path, keys: Path, monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """
    Apply the gate to explicitly registered opaque files as well as the main source bundle.

    Args:
        encrypted (Path): Staged collection generation.
        keys (Path): Independent backup.
        monkeypatch (MonkeyPatch): Separately tested host protection boundary.
        tmp_path (Path): Synthetic opaque source directory.

    Returns:
        None: Every registered encrypted payload contributes to verified coverage.
    """
    from datetime import date

    from witful.collection import managed

    monkeypatch.setattr(managed, "require_protected", lambda path: None)
    source = tmp_path / "synthetic.bin"
    source.write_bytes(b"synthetic opaque data")
    seal_file(encrypted, source, keys, "export-01", date(2030, 1, 1))
    git(encrypted, "add", CONFIG, "collection")
    assert Checker([keys]).check(snapshot(encrypted)) == 2


def test_readable_figures_fail_even_with_legacy_disclosure_approval(encrypted: Path, keys: Path) -> None:
    """
    Require encrypted personal figures even when an older configuration allowed readable publication.

    Args:
        encrypted (Path): Staged collection with disclosure disabled.
        keys (Path): Independent backup.

    Returns:
        None: A legacy disclosure option cannot bypass the encrypted publication policy.
    """
    from witful.collection.dashboard import FIGURES

    path = encrypted / f"docs/collection/{next(iter(FIGURES))}.svg"
    path.parent.mkdir(parents=True)
    path.write_text("<svg/>")
    git(encrypted, "add", "docs")
    config = evolve(load_config(encrypted), publish_figures=True)
    (encrypted / CONFIG).write_text(json.dumps(as_data(config)))
    with pytest.raises(ArtifactGateError, match="figures must be encrypted"):
        Checker([keys]).check(snapshot(encrypted))
    git(encrypted, "add", CONFIG)
    with pytest.raises(ArtifactGateError, match="figures must be encrypted"):
        Checker([keys]).check(snapshot(encrypted))


def test_artifact_symlink_is_not_followed(encrypted: Path, keys: Path, tmp_path: Path) -> None:
    """
    Reject an artifact symlink even if its target holds valid ciphertext.

    Args:
        encrypted (Path): Staged valid collection.
        keys (Path): Trusted backup.
        tmp_path (Path): External synthetic ciphertext target.

    Returns:
        None: Artifact reads remain confined to regular Git blobs.
    """
    target = tmp_path / "outside.enc.json"
    shutil.move(encrypted / SOURCE, target)
    (encrypted / SOURCE).symlink_to(target)
    git(encrypted, "add", SOURCE)
    with pytest.raises(ArtifactGateError, match="regular"):
        Checker([keys]).check(snapshot(encrypted))


def test_intermediate_plaintext_blocks_clean_tip(repository: Path) -> None:
    """
    Reject outgoing plaintext history even after a later commit deletes the private record.

    Args:
        repository (Path): Synthetic public baseline.

    Returns:
        None: Range validation inspects intermediate snapshots and annotated tag targets.
    """
    old = commit(repository, "HEAD")
    (repository / "lessons.jsonl").write_text("SYNTHETIC_PRIVATE_DATA")
    git(repository, "add", "lessons.jsonl")
    git(repository, "commit", "-m", "Private record")
    leaked = commit(repository, "HEAD")
    git(repository, "rm", "lessons.jsonl")
    git(repository, "commit", "-m", "Remove record")
    git(repository, "tag", "-a", "example", "-m", "Synthetic tag")
    assert Checker([]).check(snapshot(repository, "example")) == 0
    assert leaked in history(repository, [(old, "example")], 100)
    with pytest.raises(SystemExit) as failure:
        main(["check-artifacts", "--checkout", str(repository), "--from-ref", old, "--to-ref", "example"])
    assert failure.value.code == 2
    assert old in history(repository, [(None, "example")], 100)
    with pytest.raises(ArtifactGateError, match="budget"):
        history(repository, [(None, "example")], 1)


def test_native_input_covers_every_update_and_deletions() -> None:
    """
    Preserve all ref updates in native mode, with no implied publication for deletions.

    Returns:
        None: Native updates retain new branches, ordinary updates and annotated tag object IDs.
    """
    a, b, zero = "a" * 40, "b" * 40, "0" * 40
    value = f"refs/heads/a {a} refs/heads/a {zero}\nrefs/tags/v1 {b} refs/tags/v1 {a}\n(delete) {zero} refs/heads/c {b}\n"
    assert push_ranges(value) == ((None, a), (a, b))
    assert push_ranges(f"(delete) {zero} refs/heads/c {b}\n") == ()
    with pytest.raises(ArtifactGateError):
        push_ranges("not hook input")


def test_hook_environment_and_missing_context(repository: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Accept pre-commit ref context and reject silent fallback to an unrelated working tree.

    Args:
        repository (Path): Synthetic public branch.
        monkeypatch (MonkeyPatch): Explicit native hook environment.

    Returns:
        None: Missing context fails, while a new branch uses its supplied local ref.
    """
    monkeypatch.delenv("PRE_COMMIT_TO_REF", raising=False)
    monkeypatch.delenv("PRE_COMMIT_FROM_REF", raising=False)
    monkeypatch.delenv("PRE_COMMIT_LOCAL_BRANCH", raising=False)
    arguments = ["check-artifacts", "--checkout", str(repository), "--pre-push"]
    with pytest.raises(SystemExit):
        main(arguments)
    monkeypatch.setenv("PRE_COMMIT_LOCAL_BRANCH", "refs/heads/main")
    assert main(arguments) == 0
    with pytest.raises(SystemExit):
        main(["check-artifacts", "--checkout", str(repository), "--staged", "--from-ref", "HEAD"])


def test_shallow_history_refused(repository: Path, tmp_path: Path) -> None:
    """
    Prevent a shallow boundary from silently omitting outgoing plaintext history.

    Args:
        repository (Path): Synthetic repository to clone through its local file transport.
        tmp_path (Path): Disposable shallow clone destination.

    Returns:
        None: History checks require complete ancestry, while single revision checks remain available.
    """
    destination = tmp_path / "shallow"
    git(repository, "clone", "--depth=1", repository.as_uri(), str(destination))
    with pytest.raises(ArtifactGateError, match="full clone"):
        history(destination, [(None, "HEAD")], 100)
    assert Checker([]).check(snapshot(destination, "HEAD")) == 0


def test_installed_precommit_hook_checks_whole_index(repository: Path, tmp_path: Path) -> None:
    """
    Run the actual local hook definition when unrelated staged source hides a private record.

    Args:
        repository (Path): Synthetic public checkout.
        tmp_path (Path): Disposable minimal hook configuration.

    Returns:
        None: Pre-commit runs the always-on gate without a changed-artifact filename filter.
    """
    source = Path(__file__).resolve().parents[2] / ".pre-commit-config.yaml"
    config = yaml.safe_load(source.read_text())
    hooks = config["repos"][0]["hooks"]
    selected = next(hook for hook in hooks if hook["id"] == "witful-encrypted-artifacts")
    assert selected["always_run"] is True
    assert selected["pass_filenames"] is False
    hook_config = tmp_path / "hooks.yaml"
    hook_config.write_text(yaml.safe_dump({"repos": [{"repo": "local", "hooks": [selected]}]}))
    (repository / "lessons.jsonl").write_text("SYNTHETIC_PRIVATE_DATA")
    git(repository, "add", "lessons.jsonl")
    result = subprocess.run(
        ["pre-commit", "run", "--config", str(hook_config), "--files", "README.md"],
        cwd=repository,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 1, result.stdout.decode()
    assert b"plaintext" in result.stdout
    assert b"SYNTHETIC_PRIVATE_DATA" not in result.stdout + result.stderr


def test_encrypted_figures_pass(encrypted: Path, keys: Path) -> None:
    """
    Permit encrypted personal figures while preserving authenticated purpose binding.

    Args:
        encrypted (Path): Staged collection generation.
        keys (Path): Existing independent backup.

    Returns:
        None: Both sources and encrypted figures are authenticated without rendering or exporting.
    """
    from witful.collection.models import FIGURES

    config = load_config(encrypted)
    payload = encrypt(b"SYNTHETIC_PRIVATE_FIGURE", (keys / "collection.pub").read_bytes(), config, "figures")
    save(encrypted, FIGURES, payload, (keys / "cosign.pub").read_bytes(), config, signing_environment(keys))
    git(encrypted, "add", "collection")
    assert Checker([keys]).check(snapshot(encrypted)) == 2


def test_native_push_checks_second_reference(repository: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Reject a private second ref when the first ref is a valid public commit.

    Args:
        repository (Path): Synthetic checkout with separate public and private tips.
        monkeypatch (MonkeyPatch): Native Git hook stdin.

    Returns:
        None: Every nondeleted native ref contributes its complete outgoing range.
    """
    import io
    import sys

    old = commit(repository, "HEAD")
    (repository / "lessons.jsonl").write_text("SYNTHETIC_PRIVATE_DATA")
    git(repository, "add", "lessons.jsonl")
    git(repository, "commit", "-m", "Unpublishable record")
    new = commit(repository, "HEAD")
    value = f"refs/heads/a {old} refs/heads/a {old}\nrefs/heads/b {new} refs/heads/b {old}\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(value))
    with pytest.raises(SystemExit) as failure:
        main(["check-artifacts", "--checkout", str(repository), "--git-pre-push"])
    assert failure.value.code == 2


def test_repository_pins_are_not_an_independent_trust_root(encrypted: Path, keys: Path) -> None:
    """
    Refuse repository-controlled pins that do not match the operator's retained generation.

    Args:
        encrypted (Path): Complete staged artifact set.
        keys (Path): Trusted original backup.

    Returns:
        None: Self-consistent repository metadata cannot substitute for independent trust.
    """
    config = evolve(load_config(encrypted), signing_fingerprint="a" * 64)
    (encrypted / CONFIG).write_text(json.dumps(as_data(config)))
    git(encrypted, "add", CONFIG)
    with pytest.raises(ArtifactGateError, match="matching retained"):
        Checker([keys]).check(snapshot(encrypted))


def test_inherited_git_routing_cannot_select_another_checkout(repository: Path, monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """
    Keep explicit checkout selection independent of inherited routing and trace destinations.

    Args:
        repository (Path): Requested public checkout.
        monkeypatch (MonkeyPatch): Contaminated parent process environment.
        tmp_path (Path): Unrelated repository and trace destination.

    Returns:
        None: Inspection reads the requested objects and writes no inherited Git trace.
    """
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init")
    trace = tmp_path / "trace.txt"
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    monkeypatch.setenv("GIT_TRACE", str(trace))
    assert "README.md" in snapshot(repository).entries
    assert not trace.exists()


def test_explicit_temporary_index_remains_supported(repository: Path, monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """
    Honor Git's temporary index used for partial commits without changing the ordinary index.

    Args:
        repository (Path): Public baseline with an independently selected candidate index.
        monkeypatch (MonkeyPatch): Git's documented alternate-index environment.
        tmp_path (Path): Test-owned candidate index destination.

    Returns:
        None: The actual selected index is checked, while ordinary revision reads remain unaffected.
    """
    temporary = tmp_path / "candidate-index"
    shutil.copyfile(repository / ".git/index", temporary)
    (repository / "lessons.jsonl").write_text("SYNTHETIC_PRIVATE_DATA")
    git(repository, "add", "lessons.jsonl")
    with pytest.raises(ArtifactGateError):
        Checker([]).check(snapshot(repository))
    monkeypatch.setenv("GIT_INDEX_FILE", str(temporary))
    assert Checker([]).check(snapshot(repository)) == 0
