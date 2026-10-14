"""
Verify owner-default and recipient-key exports using real encryption and offline signatures.
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from typing import TYPE_CHECKING

import pytest
from witful.collection import export_cli, exports
from witful.collection.cli import main
from witful.collection.crypto import fingerprint
from witful.collection.exports import MANIFEST, create, restore_export, verify_export
from witful.collection.managed import snapshot
from witful.collection.material import read_keys
from witful.collection.models import CONFIG, SOURCE, load_config
from witful.knowledge.contracts import as_data, schema, structure

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch

pytestmark = pytest.mark.skipif(shutil.which("cosign") is None, reason="Real offline signatures require Cosign")
TODAY = date(2030, 1, 1)


@pytest.mark.parametrize("recipient_override", [False, True])
def test_export_restores_all_records_without_sender_secrets(
    collection: Path, generations: tuple[Path, Path], tmp_path: Path, recipient_override: bool
) -> None:
    """
    Preserve every managed record and the sender identity while selecting the intended recipient.

    Args:
        collection (Path): Synthetic sealed records, figures and additional file.
        generations (tuple[Path, Path]): Independent sender and recipient key sets.
        tmp_path (Path): Transport and protected recovery destinations.
        recipient_override (bool): Whether to target a recipient other than the operating key.

    Returns:
        None: Exact records restore with only recipient decryption material and an independent sender pin.
    """
    sender = read_keys(generations[0])
    recipient = read_keys(generations[1] if recipient_override else generations[0])
    before = snapshot(collection)
    bundle, output = tmp_path / "bundle", tmp_path / "restored"
    create(collection, sender, bundle, TODAY, recipient.public.encode() if recipient_override else None)
    pin = fingerprint(sender.signing_public.encode())
    verify_export(bundle, pin)
    restore_export(bundle, pin, recipient.private.encode(), recipient.password.encode(), output)
    assert (output / "sources/instructions.md").read_text() == "SYNTHETIC_ROTATION_RECORD"
    assert (output / "figures/provenance.json").read_text() == '{"source_commit":"synthetic"}'
    assert (output / "files/export-01").read_bytes() == b"opaque\0SYNTHETIC_EXPORT"
    config = load_config(bundle)
    assert config.signing_fingerprint == pin
    assert config.encryption_fingerprint == fingerprint(recipient.public.encode())
    assert not config.publish_figures
    assert snapshot(collection) == before
    assert json.loads((bundle / MANIFEST).read_bytes())["source"] == [as_data(item) for item in exports.digests(before)]
    for path in bundle.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert not path.stat().st_mode & 0o077
            for secret in (sender.private, sender.password, sender.signing_private, sender.signing_password, "SYNTHETIC_ROTATION_RECORD"):
                assert secret.encode() not in data
    if recipient_override:
        with pytest.raises(ValueError):
            restore_export(bundle, pin, sender.private.encode(), sender.password.encode(), tmp_path / "wrong-recipient")
        assert not (tmp_path / "wrong-recipient").exists()


@pytest.mark.parametrize("damage", ["ciphertext", "signature", "config", "missing", "extra-key", "symlink", "manifest"])
def test_export_rejects_tampering_before_plaintext_output(
    collection: Path, generations: tuple[Path, Path], tmp_path: Path, damage: str
) -> None:
    """
    Authenticate both record bytes and the closed file set before creating a recovery destination.

    Args:
        collection (Path): Synthetic sealed collection.
        generations (tuple[Path, Path]): Sender and unrelated recipient.
        tmp_path (Path): Received transport and recovery destination.
        damage (str): Mutation at one transport boundary.

    Returns:
        None: Every changed or incomplete transport is refused without releasing plaintext.
    """
    keys = read_keys(generations[0])
    bundle, output = tmp_path / "bundle", tmp_path / "restored"
    create(collection, keys, bundle, TODAY)
    if damage == "ciphertext":
        with (bundle / SOURCE).open("ab") as stream:
            stream.write(b" ")
    elif damage == "signature":
        (bundle / (MANIFEST + ".sigstore.json")).write_text("{}")
    elif damage == "config":
        data = json.loads((bundle / CONFIG).read_bytes())
        data["repository"] = "example/another"
        (bundle / CONFIG).write_text(json.dumps(data))
    elif damage == "missing":
        (bundle / (SOURCE + ".sha256")).unlink()
    elif damage == "extra-key":
        (bundle / "private.key").write_text("synthetic private addition")
    elif damage == "symlink":
        data = (bundle / SOURCE).read_bytes()
        (bundle / SOURCE).unlink()
        external = tmp_path / "external"
        external.write_bytes(data)
        (bundle / SOURCE).symlink_to(external)
    else:
        (bundle / MANIFEST).write_text("{}")
    with pytest.raises((ValueError, RuntimeError)):
        restore_export(bundle, fingerprint(keys.signing_public.encode()), keys.private.encode(), keys.password.encode(), output)
    assert not output.exists()


def test_untrusted_signer_is_rejected_before_decryption(
    collection: Path, generations: tuple[Path, Path], tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """
    Require independent sender trust rather than accepting the bundled verification key alone.

    Args:
        collection (Path): Sender's sealed collection.
        generations (tuple[Path, Path]): Sender and independent trust identity.
        tmp_path (Path): Export and recovery destinations.
        monkeypatch (MonkeyPatch): Fail if decryption is attempted before authentication.

    Returns:
        None: A mismatched signer never reaches decryption.
    """
    sender, other = (read_keys(path) for path in generations)
    bundle = tmp_path / "bundle"
    create(collection, sender, bundle, TODAY)

    def forbidden(*args: object, **kwargs: object) -> bytes:
        """
        Detect attempted plaintext processing with untrusted provenance.

        Args:
            *args (object): Rejected positional arguments.
            **kwargs (object): Rejected keyword arguments.

        Returns:
            bytes: Never returned.
        """
        pytest.fail("Decryption preceded sender authentication")

    monkeypatch.setattr(exports, "decrypt", forbidden)
    with pytest.raises(ValueError, match="signer"):
        restore_export(
            bundle, fingerprint(other.signing_public.encode()), sender.private.encode(), sender.password.encode(), tmp_path / "bad"
        )


def test_failed_export_does_not_change_current_keys_or_complete_manifest(
    collection: Path, generations: tuple[Path, Path], tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """
    Keep interrupted exports separate from complete transports and preserve the operating collection.

    Args:
        collection (Path): Current sender state.
        generations (tuple[Path, Path]): Synthetic active owner keys.
        tmp_path (Path): Partial transport.
        monkeypatch (MonkeyPatch): Inject deterministic signing failure.

    Returns:
        None: Retry requires a new destination and no active state is lost.
    """
    before, keys = snapshot(collection), read_keys(generations[0])

    def fail(*args: object, **kwargs: object) -> None:
        """
        Simulate a failed signing tool.

        Args:
            *args (object): Ignored signing inputs.
            **kwargs (object): Ignored signing options.

        Returns:
            None: Never returned successfully.
        """
        raise RuntimeError("Synthetic signing failure")

    monkeypatch.setattr(exports, "save", fail)
    with pytest.raises(RuntimeError, match="Synthetic"):
        create(collection, keys, tmp_path / "partial", TODAY)
    assert not (tmp_path / "partial" / MANIFEST).exists()
    assert snapshot(collection) == before
    with pytest.raises(ValueError, match="new directory"):
        create(collection, keys, tmp_path / "partial", TODAY)


def test_installed_defaults_and_cli_recipient_override(
    collection: Path, generations: tuple[Path, Path], tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """
    Resolve the installed active keys and exercise public CLI verification and recipient-only recovery.

    Args:
        collection (Path): Installed sealed identity.
        generations (tuple[Path, Path]): Sender and recipient backups.
        tmp_path (Path): Synthetic home, export and restoration paths.
        monkeypatch (MonkeyPatch): Supply host storage attestation already covered in protection tests.

    Returns:
        None: The CLI uses saved defaults without generating keys or requiring recipient signing secrets.
    """
    home = tmp_path / "home"
    receipt = home / "collection/.setup.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps({"repository": "example/collection", "checkout": str(collection), "keys": str(generations[0]), "command": "witful"})
    )
    receipt.chmod(0o600)
    monkeypatch.setenv("CODEX_HOME", str(home))
    sender, recipient = (read_keys(path) for path in generations)
    pin, bundle = fingerprint(sender.signing_public.encode()), tmp_path / "cli-export"
    assert main(["export", "--recipient-key", str(generations[1] / "collection.pub"), "--output", str(bundle)]) == 0
    assert main(["verify-export", "--bundle", str(bundle), "--signing-fingerprint", pin]) == 0
    # Supply only two recipient files in isolation, demonstrating that no sender or recipient signing secret is needed.
    private, password = tmp_path / "recipient.pem", tmp_path / "password"
    private.write_text(recipient.private)
    password.write_text(recipient.password)
    private.chmod(0o600)
    password.chmod(0o600)
    assert (
        main(
            [
                "restore-export",
                "--bundle",
                str(bundle),
                "--signing-fingerprint",
                pin,
                "--private-key",
                str(private),
                "--password-file",
                str(password),
                "--output",
                str(tmp_path / "cli-restored"),
            ]
        )
        == 0
    )
    root, chosen = export_cli.defaults(home, collection, generations[1], {}, TODAY)
    assert root == collection and chosen == recipient
    with pytest.raises(ValueError, match="generation"):
        create(root, chosen, tmp_path / "stale-keys", TODAY)


def test_environment_defaults_use_active_generation(collection: Path, generations: tuple[Path, Path], tmp_path: Path) -> None:
    """
    Reuse the existing environment contract without introducing alternate secret names.

    Args:
        collection (Path): Sealed identity configuration.
        generations (tuple[Path, Path]): Active and unused key sets.
        tmp_path (Path): Home without an installation receipt.

    Returns:
        None: Default selection returns the independently trusted operating keys.
    """
    keys = read_keys(generations[0])
    root, chosen = export_cli.defaults(tmp_path, collection, None, keys.environment({}), TODAY)
    assert root == collection and chosen == keys


def test_export_schema_round_trip() -> None:
    """
    Require the transport model to survive the repository's actual schema and conversion boundary.

    Returns:
        None: Closed nested records round-trip and the public schema is usable.
    """
    manifest = exports.Manifest(exports.digests({"ciphertext": b"synthetic"}), ())
    assert structure(as_data(manifest), exports.Manifest) == manifest
    assert schema(exports.Manifest)["additionalProperties"] is False


def test_expiry_blocks_new_exports_but_not_retained_recovery(collection: Path, generations: tuple[Path, Path], tmp_path: Path) -> None:
    """
    Apply the owner's signing deadline even when another recipient is selected.

    Args:
        collection (Path): Synthetic managed collection.
        generations (tuple[Path, Path]): Sender and recipient generations.
        tmp_path (Path): Export and recovery outputs.

    Returns:
        None: Historical exports recover while new expired-key exports are refused before output creation.
    """
    config = json.loads((collection / CONFIG).read_bytes())
    config["rotate_by"] = "2001-01-01"
    (collection / CONFIG).write_text(json.dumps(config))
    sender, recipient = (read_keys(path) for path in generations)
    bundle = tmp_path / "historical"
    create(collection, sender, bundle, date(2000, 1, 1))
    restore_export(
        bundle, fingerprint(sender.signing_public.encode()), sender.private.encode(), sender.password.encode(), tmp_path / "recovery"
    )
    with pytest.raises(ValueError, match="rotation is due"):
        create(collection, sender, tmp_path / "expired", TODAY, recipient.public.encode())
    assert not (tmp_path / "expired").exists()


def test_recipient_must_be_a_supported_encryption_key(collection: Path, generations: tuple[Path, Path], tmp_path: Path) -> None:
    """
    Refuse a signing public key supplied accidentally as the recipient encryption key.

    Args:
        collection (Path): Synthetic collection to copy.
        generations (tuple[Path, Path]): Separate signing and encryption material.
        tmp_path (Path): Failed export destination.

    Returns:
        None: No complete manifest is issued for an unsupported recipient.
    """
    keys = read_keys(generations[0])
    with pytest.raises(ValueError, match="RSA recipient"):
        create(collection, keys, tmp_path / "wrong-key-type", TODAY, keys.signing_public.encode())
    assert not (tmp_path / "wrong-key-type" / MANIFEST).exists()
