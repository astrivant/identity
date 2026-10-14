"""
Exercise recoverable multi-file rotation with real encryption and offline Cosign signatures.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import date
from typing import TYPE_CHECKING, Literal

import pytest
from attrs import evolve
from jsonschema import ValidationError
from witful.collection import archive, managed, material, pipeline, publication, rotation
from witful.collection.crypto import encrypt, save, verify
from witful.collection.keys import prepare, signing_environment
from witful.collection.managed import PUBLIC, RECEIPT, deadline_check, restore_file, seal_file, snapshot
from witful.collection.material import Candidate, read_candidate, read_keys
from witful.collection.models import CONFIG, FIGURES, SOURCE, Config, load_config
from witful.collection.operations import restore
from witful.collection.rotation import rotate, select_keys
from witful.knowledge.contracts import as_data
from witful.project import main as initialize

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch, TempPathFactory

pytestmark = pytest.mark.skipif(shutil.which("cosign") is None, reason="Real offline signatures require Cosign")
TODAY = date(2030, 1, 1)
DEADLINE = "2031-01-01"


@pytest.fixture(scope="module")
def generations(tmp_path_factory: TempPathFactory) -> tuple[Path, Path]:
    """
    Generate two independent synthetic backups for cryptographic integration tests.

    Args:
        tmp_path_factory (TempPathFactory): Test-owned key storage.

    Returns:
        tuple[Path, Path]: Original and replacement key directories.
    """
    root = tmp_path_factory.mktemp("rotation-keys")
    old, new = root / "old", root / "new"
    prepare(old, "example/collection")
    prepare(new, "example/collection")
    return old, new


@pytest.fixture
def collection(tmp_path: Path, generations: tuple[Path, Path], monkeypatch: MonkeyPatch) -> Path:
    """
    Build sources, derived figures, and one opaque export under the old generation.

    Args:
        tmp_path (Path): Synthetic ciphertext and source root.
        generations (tuple[Path, Path]): Independent retained key backups.
        monkeypatch (MonkeyPatch): Isolate host storage attestation, exercised separately in its own tests.

    Returns:
        Path: Three-payload collection with a non-sensitive opaque manifest.
    """
    from witful.collection import operations

    for module in (material, managed, operations, pipeline):
        monkeypatch.setattr(module, "require_protected", lambda path: None)
    root, source, figures = tmp_path / "checkout", tmp_path / "source", tmp_path / "figures"
    root.mkdir()
    (root / ".config").mkdir()
    (root / "collection").mkdir()
    figures.mkdir()
    initialize([str(source)])
    (source / "instructions.md").write_text("SYNTHETIC_ROTATION_RECORD")
    (figures / "provenance.json").write_text('{"source_commit":"synthetic"}')
    old = generations[0]
    config = prepare(old, "example/collection")
    (root / CONFIG).write_text(json.dumps(as_data(config)))
    (root / PUBLIC).write_bytes((old / "cosign.pub").read_bytes())
    entries: tuple[tuple[str, Literal["sources", "figures"], bytes], ...] = (
        (SOURCE, "sources", archive.pack(source)),
        (FIGURES, "figures", archive.pack(figures, figures=True)),
    )
    for relative, purpose, payload in entries:
        save(
            root,
            relative,
            encrypt(payload, (old / "collection.pub").read_bytes(), config, purpose),
            (old / "cosign.pub").read_bytes(),
            config,
            signing_environment(old),
        )
    extra = tmp_path / "private-export.bin"
    extra.write_bytes(b"opaque\0SYNTHETIC_EXPORT")
    seal_file(root, extra, old, "export-01", TODAY)
    return root


def test_rotation_restores_every_file_and_retains_old_history(collection: Path, generations: tuple[Path, Path], tmp_path: Path) -> None:
    """
    Rotate all three payload kinds, preserve history, and authenticate the transition with both signers.

    Args:
        collection (Path): Synthetic old-generation collection.
        generations (tuple[Path, Path]): Retained old and new keys.
        tmp_path (Path): Isolated candidate and recovery destinations.

    Returns:
        None: Exact source, figure and arbitrary file bytes recover under the intended keys only.
    """
    old, new = generations
    before = snapshot(collection)
    candidate = Candidate("example/collection", DEADLINE, read_keys(new))
    output = tmp_path / "rotation"
    current = rotate(collection, read_keys(old), candidate, output, TODAY)
    assert snapshot(collection) == before
    assert (output / "READY").is_file()
    assert not (output / "VERIFIED").exists()
    config = load_config(current)
    assert config.managed_files == ("export-01",)
    assert config.rotate_by == DEADLINE
    restore(current, new, tmp_path / "new-source", "sources")
    restore(current, new, tmp_path / "new-figures", "figures")
    restore(output / "previous", old, tmp_path / "old-source", "sources")
    restore_file(current, new, "export-01", tmp_path / "restored.bin")
    assert (tmp_path / "restored.bin").read_bytes() == b"opaque\0SYNTHETIC_EXPORT"
    assert (tmp_path / "old-source/instructions.md").read_bytes() == (tmp_path / "new-source/instructions.md").read_bytes()
    assert (tmp_path / "new-figures/provenance.json").read_text() == '{"source_commit":"synthetic"}'
    verify(current / RECEIPT, new / "cosign.pub", config)
    verify(output / "previous/collection/next-rotation.json", old / "cosign.pub", load_config(output / "previous"))
    receipt = json.loads((current / RECEIPT).read_bytes())
    assert receipt["previous"][SOURCE] == hashlib.sha256(before[SOURCE]).hexdigest()
    assert receipt["history_policy"] == "retain-old-keys"
    with pytest.raises(ValueError):
        restore(current, old, tmp_path / "wrong", "sources")
    with pytest.raises(ValueError):
        restore(output / "previous", new, tmp_path / "wrong-history", "sources")
    assert all(b"SYNTHETIC_ROTATION_RECORD" not in path.read_bytes() for path in output.rglob("*") if path.is_file())


def test_failure_and_retry_preserve_the_active_generation(
    collection: Path,
    generations: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Inject a signing failure and require an untouched source and a fresh explicit retry destination.

    Args:
        collection (Path): Synthetic active ciphertext.
        generations (tuple[Path, Path]): Retained test keys.
        tmp_path (Path): Candidate directories.
        monkeypatch (MonkeyPatch): Deterministic signing failure boundary.

    Returns:
        None: Failed candidates cannot be published and a retry succeeds without losing the old generation.
    """
    before = snapshot(collection)
    candidate = Candidate("example/collection", DEADLINE, read_keys(generations[1]))
    original = save

    def fail(*args: object, **kwargs: object) -> None:
        """
        Reject signing before a candidate can become complete.

        Args:
            *args (object): Ignored positional arguments.
            **kwargs (object): Ignored keyword arguments.

        Returns:
            None: Never returns successfully.
        """
        raise ValueError("synthetic signing failure")

    monkeypatch.setattr(rotation, "save", fail)
    with pytest.raises(ValueError, match="synthetic"):
        rotate(collection, read_keys(generations[0]), candidate, tmp_path / "failed", TODAY)
    assert snapshot(collection) == before
    assert not (tmp_path / "failed/READY").exists()
    monkeypatch.setattr(rotation, "save", original)
    with pytest.raises(ValueError, match="new rotation output"):
        rotate(collection, read_keys(generations[0]), candidate, tmp_path / "failed", TODAY)
    rotate(collection, read_keys(generations[0]), candidate, tmp_path / "retry", TODAY)


@pytest.mark.parametrize("failure", ["checksum", "signature", "missing", "unregistered", "symlink"])
def test_bad_inventory_or_authentication_cannot_rotate(
    collection: Path,
    generations: tuple[Path, Path],
    tmp_path: Path,
    failure: str,
) -> None:
    """
    Refuse damaged or ambiguous encrypted inventories before issuing a ready candidate.

    Args:
        collection (Path): Synthetic active ciphertext.
        generations (tuple[Path, Path]): Retained test keys.
        tmp_path (Path): Candidate destination.
        failure (str): Deterministic invalid state.

    Returns:
        None: No incomplete or unregistered inventory is silently omitted.
    """
    if failure == "checksum":
        (collection / (SOURCE + ".sha256")).write_text("0" * 64)
    elif failure == "signature":
        (collection / SOURCE).write_bytes((collection / SOURCE).read_bytes() + b" ")
    elif failure == "missing":
        (collection / "collection/files/export-01.enc.json").unlink()
    elif failure == "unregistered":
        (collection / "collection/unknown.enc.json").write_bytes((collection / SOURCE).read_bytes())
    else:
        path = collection / "collection/files/export-01.enc.json"
        path.unlink()
        path.symlink_to(collection / SOURCE)
    candidate = Candidate("example/collection", DEADLINE, read_keys(generations[1]))
    with pytest.raises(ValueError):
        rotate(collection, read_keys(generations[0]), candidate, tmp_path / "rejected", TODAY)
    assert not (tmp_path / "rejected/READY").exists()


def test_candidate_adoption_is_idempotent_and_invalid_candidates_fail_closed(
    collection: Path,
    generations: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    """
    Keep old secrets for history while subsequent runs use the already adopted candidate.

    Args:
        collection (Path): Active collection before rotation.
        generations (tuple[Path, Path]): Old and replacement keys.
        tmp_path (Path): Candidate output.

    Returns:
        None: No repeat rotation, deadline extension, invalid fallback, or mixed-generation acceptance occurs.
    """
    old, new = read_keys(generations[0]), read_keys(generations[1])
    candidate = Candidate("example/collection", DEADLINE, new)
    env = old.environment({})
    env["WITFUL_COLLECTION_NEXT_KEYS"] = json.dumps(as_data(candidate))
    active, pending = select_keys(collection, env, TODAY)
    assert active == old and pending == candidate
    current = rotate(collection, old, candidate, tmp_path / "candidate", TODAY)
    active, pending = select_keys(current, env, TODAY)
    assert active == new and pending is None
    env["WITFUL_COLLECTION_NEXT_KEYS"] = json.dumps(as_data(evolve(candidate, rotate_by="2032-01-01")))
    with pytest.raises(ValueError, match="extend"):
        select_keys(current, env, TODAY)
    env["WITFUL_COLLECTION_NEXT_KEYS"] = "{}"
    with pytest.raises(ValidationError) as rejected:
        select_keys(collection, env, TODAY)
    assert "PRIVATE KEY" not in str(rejected.value)
    env["WITFUL_COLLECTION_NEXT_KEYS"] = json.dumps(as_data(evolve(candidate, keys=evolve(new, public=old.public))))
    with pytest.raises(ValueError, match="pair differs"):
        select_keys(collection, env, TODAY)


def test_deadlines_stop_writes_but_allow_retained_recovery(collection: Path, generations: tuple[Path, Path], tmp_path: Path) -> None:
    """
    Rotate even after the old deadline without disabling historical decryption.

    Args:
        collection (Path): Synthetic active generation.
        generations (tuple[Path, Path]): Test key generations.
        tmp_path (Path): Candidate and recovery paths.

    Returns:
        None: Expired key use is restricted to recovery and rotation, with no implicit renewal.
    """
    expired = evolve(load_config(collection), rotate_by="2029-12-31")
    (collection / CONFIG).write_text(json.dumps(as_data(expired)))
    with pytest.raises(ValueError, match="rotation is due"):
        deadline_check(expired, TODAY)
    restore(collection, generations[0], tmp_path / "historical", "sources")
    rotate(
        collection, read_keys(generations[0]), Candidate("example/collection", DEADLINE, read_keys(generations[1])), tmp_path / "new", TODAY
    )
    with pytest.raises(ValueError, match="deadline"):
        read_candidate(
            json.dumps(as_data(Candidate("example/collection", "2030-01-01", read_keys(generations[1])))), "example/collection", TODAY
        )


def test_pipeline_candidate_is_atomic_verified_and_refuses_changed_bytes(
    collection: Path,
    generations: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Prepare with real cryptography and inspect the sole optimistic publication mutation through a fake host.

    Args:
        collection (Path): Synthetic three-payload collection.
        generations (tuple[Path, Path]): Old and new key material.
        tmp_path (Path): Private candidate root.
        monkeypatch (MonkeyPatch): GitHub visibility, event authorization and API boundary only.

    Returns:
        None: One verified API commit owns all paths, and changes after verification never reach the host.
    """
    monkeypatch.setattr(pipeline, "authorize", lambda checkout, env: None)
    from witful.collection import operations

    monkeypatch.setattr(operations, "private_repository", lambda repository: None)
    env = read_keys(generations[0]).environment(
        {
            "PATH": os.environ["PATH"],
            "GITHUB_SHA": "a" * 40,
            "GITHUB_REPOSITORY": "example/collection",
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_REF": "refs/heads/main",
            "WITFUL_SECURE_TEMP": str(tmp_path),
        }
    )
    env["WITFUL_COLLECTION_NEXT_KEYS"] = json.dumps(as_data(Candidate("example/collection", DEADLINE, read_keys(generations[1]))))
    output = tmp_path / "prepared"
    current = pipeline.prepare(collection, output, env, TODAY)
    assert (output / "VERIFIED").is_file()
    assert (output / "rotated" / RECEIPT).is_file()
    restore(current, generations[1], tmp_path / "pipeline-figures", "figures")
    provenance = json.loads((tmp_path / "pipeline-figures/provenance.json").read_bytes())
    assert provenance["source_ciphertext_sha256"] == hashlib.sha256((current / SOURCE).read_bytes()).hexdigest()
    contents = publication.publication_files(current)
    requests: list[dict[str, object]] = []

    def host(arguments: list[str], *, data: bytes | None = None, env: dict[str, str] | None = None) -> bytes:
        """
        Model one GitHub-signed commit and its independently read-back tree.

        Args:
            arguments (list[str]): Expected gh API invocation.
            data (bytes | None): Structured request body.
            env (dict[str, str] | None): Scoped nonlogged credentials.

        Returns:
            bytes: Synthetic immutable host response.
        """
        if "graphql" in arguments:
            assert data is not None
            request = json.loads(data)
            requests.append(request)
            assert request["variables"]["input"]["expectedHeadOid"] == "a" * 40
            additions = request["variables"]["input"]["fileChanges"]["additions"]
            assert {item["path"] for item in additions} == set(contents)
            return json.dumps({"data": {"createCommitOnBranch": {"commit": {"oid": "b" * 40}}}}).encode()
        if ".commit.verification.verified" in arguments:
            return b"true\n"
        return json.dumps(
            {
                "truncated": False,
                "tree": [
                    {
                        "type": "blob",
                        "path": name,
                        "sha": hashlib.sha1(f"blob {len(value)}\0".encode() + value, usedforsecurity=False).hexdigest(),
                    }
                    for name, value in contents.items()
                ],
            }
        ).encode()

    monkeypatch.setattr(publication, "run", host)
    assert publication.publish(collection, output, env) == "b" * 40
    assert len(requests) == 1
    (current / SOURCE).write_bytes((current / SOURCE).read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed after verification"):
        publication.publish(collection, output, env)
    assert len(requests) == 1


def test_untrusted_events_are_rejected_before_key_loading(collection: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Reject PR and foreign-repository invocations before contacting GitHub or parsing secrets.

    Args:
        collection (Path): Synthetic configured collection.
        monkeypatch (MonkeyPatch): Fail if the network boundary is reached.

    Returns:
        None: Untrusted contexts cannot enter rotation even with candidate credentials present.
    """

    def unexpected(repository: str) -> None:
        """
        Make an unexpected external call observable.

        Args:
            repository (str): Ignored destination.

        Returns:
            None: Never returns successfully.
        """
        pytest.fail("Untrusted event reached repository access")

    monkeypatch.setattr(pipeline, "private_repository", unexpected)
    for event, repository in (("pull_request", "example/collection"), ("push", "other/collection")):
        with pytest.raises(ValueError, match="private main"):
            pipeline.authorize(collection, {"GITHUB_EVENT_NAME": event, "GITHUB_REF": "refs/heads/main", "GITHUB_REPOSITORY": repository})


def test_input_change_invalidates_candidate(
    collection: Path,
    generations: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Detect a writer changing active configuration while the candidate is being signed.

    Args:
        collection (Path): Synthetic old generation.
        generations (tuple[Path, Path]): Old and new backups.
        tmp_path (Path): Candidate destination.
        monkeypatch (MonkeyPatch): Deterministic concurrent change boundary.

    Returns:
        None: Source edits survive, while a stale candidate never receives its ready marker.
    """
    original = save

    def changed(root: Path, relative: str, content: bytes, public: bytes, config: Config, env: dict[str, str]) -> None:
        """
        Change the source after signing without timing-dependent threads.

        Args:
            root (Path): Candidate directory.
            relative (str): Output path.
            content (bytes): Ciphertext bytes.
            public (bytes): Verification key.
            config (Config): Candidate pins.
            env (dict[str, str]): Signing environment.

        Returns:
            None: Signature completes and the separate source gains an external edit.
        """
        original(root, relative, content, public, config, env)
        (collection / CONFIG).write_bytes((collection / CONFIG).read_bytes() + b" ")

    monkeypatch.setattr(rotation, "save", changed)
    with pytest.raises(RuntimeError, match="changed during rotation"):
        rotate(
            collection,
            read_keys(generations[0]),
            Candidate("example/collection", DEADLINE, read_keys(generations[1])),
            tmp_path / "stale",
            TODAY,
        )
    assert not (tmp_path / "stale/READY").exists()
    assert (collection / CONFIG).read_bytes().endswith(b" ")


def test_candidate_export_is_private_exclusive_and_outside_git(
    generations: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Persist a complete recoverable candidate without permitting overwrites or Git placement.

    Args:
        generations (tuple[Path, Path]): Existing synthetic key backups.
        tmp_path (Path): New private output paths.
        monkeypatch (MonkeyPatch): Host storage boundary tested separately.

    Returns:
        None: Private file contents round-trip and rejected exports preserve their original bytes.
    """
    monkeypatch.setattr(material, "require_protected", lambda path: None)
    output = tmp_path / "candidate.json"
    material.export_candidate(generations[1], "example/collection", DEADLINE, output, TODAY)
    assert output.stat().st_mode & 0o077 == 0
    candidate = read_candidate(output.read_text(), "example/collection", TODAY)
    assert candidate.keys == read_keys(generations[1])
    before = output.read_bytes()
    with pytest.raises(ValueError, match="new private output"):
        material.export_candidate(generations[1], "example/collection", DEADLINE, output, TODAY)
    assert output.read_bytes() == before
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".git").mkdir()
    with pytest.raises(ValueError, match="outside Git"):
        material.export_candidate(generations[1], "example/collection", DEADLINE, repository / "secret.json", TODAY)
    assert not (repository / "secret.json").exists()


@pytest.mark.parametrize("retained", ["encryption", "signing"])
def test_a_shared_deadline_cannot_renew_a_retained_key(
    collection: Path,
    generations: tuple[Path, Path],
    tmp_path: Path,
    retained: str,
) -> None:
    """
    Reject partial replacement that would extend the retained member of a generation.

    Args:
        collection (Path): Synthetic active collection.
        generations (tuple[Path, Path]): Independently generated pairs.
        tmp_path (Path): Candidate output parent.
        retained (str): Key purpose deliberately kept from the old generation.

    Returns:
        None: Neither partial key replacement can silently renew the other's shared deadline.
    """
    old, new = read_keys(generations[0]), read_keys(generations[1])
    if retained == "encryption":
        mixed = evolve(new, private=old.private, public=old.public, password=old.password)
    else:
        mixed = evolve(new, signing_private=old.signing_private, signing_public=old.signing_public, signing_password=old.signing_password)
    with pytest.raises(ValueError, match="Replace both keys"):
        rotate(collection, old, Candidate("example/collection", DEADLINE, mixed), tmp_path / "renewal", TODAY)
    assert not (tmp_path / "renewal").exists()
