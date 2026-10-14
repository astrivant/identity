"""
Exercise actual Git bindings, private receipt storage, adapter denial, and source archive compatibility.
"""

from __future__ import annotations

import json
import subprocess
import time
from typing import TYPE_CHECKING

import pytest
from attrs import evolve
from witful.collection import archive
from witful.completion.storage import identity, snapshots
from witful.context import cli, storage
from witful.context.core import digest
from witful.context.models import Decision, Descriptor, Mapping, Receipt, Review, Scope
from witful.knowledge.contracts import as_data, structure
from witful.knowledge.models import Catalog, DisciplineSpec, SkillSpec
from witful.project import main as initialize

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import CaptureFixture, MonkeyPatch
    from witful.completion.models import Workspace


@pytest.fixture
def collection(tmp_path: Path) -> Path:
    """
    Create a committed synthetic collection with one skill and isolated Git identity.

    Args:
        tmp_path (Path): Test-owned working storage.

    Returns:
        Path: Committed fixture with ignored private receipt storage.
    """
    root = tmp_path / "collection"
    initialize([str(root)])
    catalog = Catalog(
        "identity:local", "Synthetic", disciplines=(DisciplineSpec("discipline:one", "Practice", (SkillSpec("skill:one", "Work"),)),)
    )
    (root / "knowledge/catalog.json").write_text(json.dumps(as_data(catalog)))
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "Synthetic collection",
        ],
        check=True,
    )
    return root


def inputs(root: Path) -> tuple[list[str], Path]:
    """
    Prepare explicit synthetic descriptor and mapping inputs in ignored runtime storage.

    Args:
        root (Path): Synthetic committed collection.

    Returns:
        tuple[list[str], Path]: Shared CLI arguments and an unused safe receipt destination.
    """
    tree = identity(root)
    scope = Scope(tree.id, "collection:fixture", "domain:fixture", "access:1")
    directory = root / ".witful/context"
    directory.mkdir(parents=True)
    mapping, descriptor = directory / "mapping.json", directory / "descriptor.json"
    mapping.write_text(json.dumps(as_data(Mapping(scope, digest(tree)))))
    descriptor.write_text(json.dumps(as_data(Descriptor(scope, "task:one", "edit", "write", "context:1", ("skill:one",)))))
    return ["--mapping", str(mapping), "--descriptor", str(descriptor), "--observed-at", str(int(time.time()))], directory / "receipt.json"


def test_cli_plan_review_check_and_dirty_workspace(collection: Path, capsys: CaptureFixture[str]) -> None:
    """
    Recompute real source and workspace bindings and reject a receipt after actual edits.

    Args:
        collection (Path): Synthetic committed collection.
        capsys (CaptureFixture[str]): Captured adapter summaries.

    Returns:
        None: Complete individual review succeeds, while missing context and stale files fail closed.
    """
    prefix = ["--repo", str(collection)]
    common, output = inputs(collection)
    assert cli.main([*prefix, "plan", *common, "--output", str(output)]) == 1
    receipt = structure(json.loads(output.read_text()), Receipt)
    assert receipt.state == "incomplete" and receipt.descriptor is not None
    assert receipt.source_revision and receipt.mapping_digest and receipt.limits
    assert output.stat().st_mode & 0o777 == 0o600
    review = output.with_name("review.json")
    review.write_text(
        json.dumps(
            as_data(Review(tuple(Decision(item.id, "applicable", "Synthetic task scope", "fixture:review") for item in receipt.candidates)))
        )
    )
    reviewed = [*common, "--decisions", str(review)]
    assert cli.main([*prefix, "resolve", *reviewed, "--output", str(output)]) == 2
    assert cli.main([*prefix, "resolve", *reviewed, "--output", str(output), "--replace"]) == 0
    verify = [*prefix, "check", *reviewed, "--input", str(output)]
    assert cli.main(verify) == 1
    assert cli.main([*verify, "--context-present"]) == 0
    (collection / "changed.txt").write_text("Changed task workspace")
    assert cli.main([*verify, "--context-present"]) == 1
    assert "receipt_changed" in capsys.readouterr().out


def test_scope_denial_does_not_read_the_collection(collection: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]) -> None:
    """
    Reject mismatched access scopes before any collection capture or receipt read.

    Args:
        collection (Path): Synthetic source root.
        monkeypatch (MonkeyPatch): Detect forbidden source access.
        capsys (CaptureFixture[str]): Verify a redacted diagnostic.

    Returns:
        None: The adapter reports unavailable access without exposing target metadata.
    """
    common, output = inputs(collection)
    descriptor = output.with_name("descriptor.json")
    value = structure(json.loads(descriptor.read_text()), Descriptor)
    descriptor.write_text(json.dumps(as_data(evolve(value, scope=evolve(value.scope, domain="hidden:foreign")))))

    def forbidden(*args: object, **kwargs: object) -> None:
        """
        Fail on any unexpected capture after access denial.

        Args:
            *args (object): Unused capture arguments.
            **kwargs (object): Unused capture options.

        Returns:
            None: Always fails the test.
        """
        pytest.fail("Denied collection was read")

    monkeypatch.setattr(cli, "capture", forbidden)
    assert cli.main(["--repo", str(collection), "plan", *common, "--output", str(output)]) == 2
    result = capsys.readouterr().out
    assert "access_unavailable" in result and "hidden:foreign" not in result
    assert not output.exists()


def test_receipt_paths_and_inputs_are_bounded(collection: Path, tmp_path: Path) -> None:
    """
    Reject escaped/symlinked receipt storage and oversized inputs without altering their target.

    Args:
        collection (Path): Synthetic root with an ignored runtime directory.
        tmp_path (Path): Test-owned external paths.

    Returns:
        None: Only private in-collection receipts can be persisted.
    """
    _, output = inputs(collection)
    with pytest.raises(ValueError):
        storage.destination(collection, tmp_path / "outside.json")
    target = tmp_path / "target.json"
    target.write_text("unchanged")
    output.symlink_to(target)
    with pytest.raises(ValueError):
        storage.destination(collection, output)
    assert target.read_text() == "unchanged"
    output.unlink()
    output.write_text("existing")
    output.chmod(0o644)
    storage.destination(collection, output)
    assert output.stat().st_mode & 0o777 == 0o600
    target.write_bytes(b" " * (storage.MAX_INPUT_BYTES + 1))
    with pytest.raises(ValueError, match="limit"):
        storage.read(target)


def test_archive_keeps_reviewed_mapping_but_excludes_runtime_receipts(collection: Path, tmp_path: Path) -> None:
    """
    Preserve the additive sidecar through existing authenticated archive serialization.

    Args:
        collection (Path): Synthetic source root.
        tmp_path (Path): New restore destination parent.

    Returns:
        None: Reviewed rules round-trip, runtime text stays excluded, and malformed mappings fail validation.
    """
    _, output = inputs(collection)
    mapping = output.with_name("mapping.json")
    source = collection / "knowledge/context.json"
    source.write_bytes(mapping.read_bytes())
    output.write_text("runtime text must remain local")
    archive.validate(collection)
    restored = tmp_path / "restored"
    archive.unpack(archive.pack(collection), restored)
    assert (restored / "knowledge/context.json").read_bytes() == source.read_bytes()
    assert not (restored / ".witful").exists()
    archive.validate(restored)
    source.write_text('{"unknown":true}')
    from jsonschema import ValidationError

    with pytest.raises(ValidationError):
        archive.validate(collection)


def test_capture_rejects_changed_journal(collection: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Detect a source edit while the adapter fingerprints workspaces.

    Args:
        collection (Path): Synthetic source root.
        monkeypatch (MonkeyPatch): Inject an observed concurrent source change.

    Returns:
        None: A mixed source observation cannot produce a receipt.
    """
    original = snapshots

    def change(roots: tuple[Path, ...]) -> tuple[Workspace, ...]:
        """
        Modify the source between compilation and the final consistency read.

        Args:
            roots (tuple[Path, ...]): Explicit selected workspaces.

        Returns:
            tuple[Workspace, ...]: Real fingerprints after the injected change.
        """
        (collection / "lessons.jsonl").write_text("\n")
        return original(roots)

    monkeypatch.setattr(storage, "snapshots", change)
    with pytest.raises(RuntimeError, match="changed"):
        storage.capture(collection, (), 10, 20)


def test_managed_protection_precedes_inputs(collection: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Preserve managed collection protection at the new CLI boundary.

    Args:
        collection (Path): Synthetic source root.
        monkeypatch (MonkeyPatch): Model a failed existing volume attestation.

    Returns:
        None: An unverified storage policy blocks receipt creation.
    """
    from witful.exceptions import StorageProtectionError

    common, output = inputs(collection)

    def deny(*paths: Path) -> None:
        """
        Reject the collection and explicit input paths under the existing protection contract.

        Args:
            *paths (Path): Actual protected inputs selected by the adapter.

        Returns:
            None: Never returns normally.

        Raises:
            StorageProtectionError: The synthetic storage check is unavailable.
        """
        assert collection in paths
        assert output.with_name("descriptor.json") in paths
        raise StorageProtectionError("Synthetic unverified storage")

    monkeypatch.setattr(cli, "check_collection", deny)
    assert cli.main(["--repo", str(collection), "plan", *common, "--output", str(output)]) == 2
    assert not output.exists()
