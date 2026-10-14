"""
Export authenticated collection snapshots for the active owner or a separate encryption recipient.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Literal

from attrs import evolve, frozen

from witful.collection import archive
from witful.collection.crypto import decrypt, encrypt, fingerprint, save, verify
from witful.collection.managed import PUBLIC, SUFFIXES, FileRecord, deadline_check, payloads, recover, snapshot
from witful.collection.models import CONFIG, Config, file_path, load_config, parse_config
from witful.collection.protection import require_protected
from witful.collection.rotation import trusted, write_snapshot
from witful.files import replace_file
from witful.knowledge.contracts import as_data, structure
from witful.life.contracts import canonical

if TYPE_CHECKING:
    from datetime import date

    from witful.collection.material import Material

MANIFEST = "export.json"


@frozen
class Digest:
    """
    Describe one transport file using schema-supported closed records.

    Attributes:
        path (str): Relative transport name.
        sha256 (str): Digest of ciphertext or public metadata.
    """

    path: str
    sha256: str


@frozen
class Manifest:
    """
    Bind the complete export set and its source ciphertext to one offline signature.

    Attributes:
        files (tuple[Digest, ...]): Exact transport paths and SHA-256 digests, including configuration.
        source (tuple[Digest, ...]): Input ciphertext/public-metadata digests; no plaintext hashes or local paths.
        format (Literal["witful-identity-export"]): Separates exports from ordinary collection snapshots.
        version (Literal[1]): Supported export contract.
    """

    files: tuple[Digest, ...]
    source: tuple[Digest, ...]
    format: Literal["witful-identity-export"] = "witful-identity-export"
    version: Literal[1] = 1


def digests(contents: dict[str, bytes]) -> tuple[Digest, ...]:
    """
    Hash the exact captured bytes without consulting mutable paths again.

    Args:
        contents (dict[str, bytes]): Validated transport file map.

    Returns:
        tuple[Digest, ...]: Deterministically ordered integrity records.
    """
    return tuple(Digest(name, hashlib.sha256(data).hexdigest()) for name, data in sorted(contents.items()))


def read_file(path: Path, *, private: bool = False) -> bytes:
    """
    Read bounded key or manifest metadata without following a final symlink.

    Args:
        path (Path): Explicit local input.
        private (bool): Require protected storage and owner-only permissions for secret inputs.

    Returns:
        bytes: Metadata bounded to 256 KiB.

    Raises:
        ValueError: The input is not a regular bounded file or has unsafe secret permissions.
    """
    if private:
        require_protected(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 262144:
        raise ValueError("Expected a bounded regular metadata file")
    if private and path.stat().st_mode & 0o077:
        raise ValueError("Private keys and password files require owner-only permissions")
    data = path.read_bytes()
    if len(data) > 262144:
        raise ValueError("Metadata changed beyond its size limit")
    return data


def capture(root: Path) -> dict[str, bytes]:
    """
    Capture a closed export tree before verification or decryption can inspect it.

    Args:
        root (Path): Untrusted received directory.

    Returns:
        dict[str, bytes]: Bounded immutable ciphertext and public metadata, including signed manifest.

    Raises:
        ValueError: Additional files, symlinks, rotation metadata or missing transport files occur.
    """
    read_file(root / CONFIG)
    contents = snapshot(root)
    config = parse_config(contents[CONFIG])
    expected = {CONFIG, PUBLIC, *(name + suffix for name in payloads(root, config) for suffix in SUFFIXES)}
    expected.update(MANIFEST + suffix for suffix in SUFFIXES)
    discovered: set[str] = set()
    directories = {str(parent) for name in expected for parent in Path(name).parents if str(parent) != "."}

    # Reject even unreferenced additions: a transport must not carry keys or unrelated plaintext beside valid ciphertext.
    for path in root.rglob("*"):
        name = path.relative_to(root).as_posix()
        if path.is_symlink() or (path.is_dir() and name not in directories):
            raise ValueError("Unexpected export path")
        if not path.is_dir():
            discovered.add(name)
    if discovered != expected or set(contents) != expected - {MANIFEST + suffix for suffix in SUFFIXES}:
        raise ValueError("Export inventory differs from its closed transport contract")
    contents.update({MANIFEST + suffix: read_file(root / (MANIFEST + suffix)) for suffix in SUFFIXES})
    return contents


def verify_captured(root: Path, signing_fingerprint: str) -> Config:
    """
    Authenticate the full immutable export using an independently obtained signer fingerprint.

    Args:
        root (Path): Private staging directory populated from capture, never a mutable received tree.
        signing_fingerprint (str): Expected sender fingerprint obtained outside the bundle.

    Returns:
        Config: Authenticated source identity and encryption recipient.

    Raises:
        ValueError: Signer, complete inventory, checksum, or export policy differs.
    """
    config = load_config(root)
    if config.signing_fingerprint != signing_fingerprint or config.publish_figures:
        raise ValueError("Export signer differs or requests plaintext figure publication")
    verify(root / MANIFEST, root / PUBLIC, config)
    content = (root / MANIFEST).read_bytes()
    if hashlib.sha256(content).hexdigest() != (root / (MANIFEST + ".sha256")).read_text().strip():
        raise ValueError("Export manifest checksum differs")
    manifest = structure(json.loads(content), Manifest)
    if manifest.files != digests(snapshot(root)):
        raise ValueError("Signed export file inventory differs")
    for relative in payloads(root, config):
        verify(root / relative, root / PUBLIC, config)
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != (root / (relative + ".sha256")).read_text().strip():
            raise ValueError("Export payload checksum differs")
    return config


def create(checkout: Path, keys: Material, output: Path, today: date, recipient: bytes | None = None) -> None:
    """
    Re-encrypt all current managed records without changing the active identity or its signer.

    Args:
        checkout (Path): Current sealed collection whose allowlisted sources, figures and managed files are selected.
        keys (Material): Active owner's independently retained or projected key generation.
        output (Path): New transport directory outside the collection.
        today (date): Explicit UTC clock for the active signing generation's deadline.
        recipient (bytes | None): Optional trusted RSA public key; defaults to the active encryption key.

    Returns:
        None: Complete signed export directory; no network publication or key generation occurs.

    Raises:
        ValueError: Input trust, key strength, deadline, size or output destination is invalid.
        RuntimeError: Current inputs change before export completion.
    """
    before = snapshot(checkout)
    config = parse_config(before[CONFIG])
    trusted(config, keys)
    deadline_check(config, today)
    public = keys.public.encode() if recipient is None else recipient
    exported = evolve(config, encryption_fingerprint=fingerprint(public), publish_figures=False)
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(checkout.resolve()):
        raise ValueError("Export requires a new directory outside the collection")

    # Capturing first binds verification and use to identical inputs, including the inventory's configuration.
    with TemporaryDirectory(prefix="witful-export-") as temporary:
        original = Path(temporary) / "original"
        write_snapshot(original, before)
        output.mkdir(mode=0o700, parents=True)
        replace_file(output / CONFIG, canonical(as_data(exported)) + b"\n", expected=None)
        replace_file(output / PUBLIC, keys.signing_public.encode(), expected=None)
        env = keys.environment(dict(os.environ))
        for relative, purpose in payloads(original, config).items():
            plain = recover(original, config, keys, relative, purpose)
            ciphertext = encrypt(plain, public, exported, purpose)
            save(output, relative, ciphertext, keys.signing_public.encode(), exported, env)
            # Default-key exports can additionally prove recovery locally; recipient keys remain with the recipient.
            if exported.encryption_fingerprint == config.encryption_fingerprint:
                if recover(output, exported, keys, relative, purpose) != plain:
                    raise ValueError("Export restoration differs from the source")
        if snapshot(checkout) != before:
            raise RuntimeError("Collection changed during export; retry from a current snapshot")
        manifest = Manifest(digests(snapshot(output)), digests(before))
        # The manifest is written last, so an interrupted export cannot pass complete-set verification.
        save(output, MANIFEST, canonical(as_data(manifest)) + b"\n", keys.signing_public.encode(), exported, env)
    verify_export(output, config.signing_fingerprint)


def verify_export(bundle: Path, signing_fingerprint: str) -> None:
    """
    Verify a received export without possessing any encryption or signing private key.

    Args:
        bundle (Path): Export directory received from the sender.
        signing_fingerprint (str): Independently trusted sender fingerprint.

    Returns:
        None: Exact bundle contents and signatures match the trusted sender.
    """
    contents = capture(bundle)
    with TemporaryDirectory(prefix="witful-verify-export-") as temporary:
        root = Path(temporary) / "snapshot"
        write_snapshot(root, contents)
        verify_captured(root, signing_fingerprint)


def restore_export(bundle: Path, signing_fingerprint: str, private: bytes, password: bytes, output: Path) -> None:
    """
    Restore verified records using only the recipient's encrypted RSA private key and password.

    Args:
        bundle (Path): Received closed export directory.
        signing_fingerprint (str): Sender identity verified through an independent channel.
        private (bytes): Recipient's encrypted RSA PEM private key; never the sender's signing key.
        password (bytes): Exact RSA password bytes, without trimming or logging.
        output (Path): New plaintext destination on protected storage, outside Git.

    Returns:
        None: Sources, optional figures, and opaque files are restored under separate subdirectories.

    Raises:
        ValueError: Trust, decryption, archive membership or output safety checks fail.
    """
    require_protected(output)
    if (
        output.exists()
        or output.is_symlink()
        or output.resolve().is_relative_to(bundle.resolve())
        or any((parent / ".git").exists() for parent in (output, *output.parents))
    ):
        raise ValueError("Restore requires a new protected destination outside Git and the bundle")
    contents = capture(bundle)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Temporary plaintext stays on the same protected volume and is validated before creating the user's destination.
    with TemporaryDirectory(prefix=".witful-restore-", dir=output.parent) as temporary:
        root, restored = Path(temporary) / "snapshot", Path(temporary) / "restored"
        write_snapshot(root, contents)
        config = verify_captured(root, signing_fingerprint)
        restored.mkdir(mode=0o700)
        for relative, purpose in payloads(root, config).items():
            plain = decrypt((root / relative).read_bytes(), private, password, config, purpose)
            if purpose == "files":
                record = structure(json.loads(plain), FileRecord)
                if file_path(record.name) != relative:
                    raise ValueError("Opaque export identity differs from its authenticated path")
                replace_file(restored / "files" / record.name, base64.b64decode(record.content, validate=True), expected=None)
            else:
                archive.unpack(plain, restored / purpose, figures=purpose == "figures")
        archive.validate(restored / "sources")
        output.mkdir(mode=0o700)
        for path in sorted(restored.rglob("*")):
            if path.is_file():
                replace_file(output / path.relative_to(restored), path.read_bytes(), expected=None)
