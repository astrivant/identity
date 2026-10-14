"""
Inventory encrypted ownership and preserve explicitly registered opaque files.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import date
from pathlib import Path
from typing import Literal

from attrs import evolve, frozen

from witful.collection.crypto import decrypt, encrypt, save, verify
from witful.collection.material import Material, read_keys
from witful.collection.models import CONFIG, FIGURES, MAX_BYTES, SOURCE, Config, file_path, load_config
from witful.collection.protection import require_protected
from witful.files import replace_file
from witful.knowledge.contracts import as_data, structure

PUBLIC = "collection/cosign.pub"
PINS = "collection/key-fingerprints.json"
RECEIPT = "collection/rotation.json"
SUFFIXES = ("", ".sigstore.json", ".sha256")


@frozen
class FileRecord:
    """
    Authenticate an opaque file identifier inside its encrypted payload.

    Attributes:
        name (str): Reviewed opaque identifier bound to its transport path.
        content (str): Base64 file bytes, never a source filename.
    """

    name: str
    content: str


def deadline_check(config: Config, today: date) -> None:
    """
    Refuse new protected writes at expiry while leaving historical reads available.

    Args:
        config (Config): Active key generation's optional deadline.
        today (date): UTC clock captured by the caller.

    Returns:
        None: Unexpired writes may proceed, with a thirty-day reminder when due.

    Raises:
        ValueError: The configured rotation deadline has arrived.
    """
    if config.rotate_by is None:
        return
    days = (date.fromisoformat(config.rotate_by) - today).days
    if days <= 0:
        raise ValueError("Key rotation is due; stage replacement keys before new protected writes")
    if days <= 30:
        print(f"Collection keys need rotation within {days} days; see docs/key-rotation.md.")


def payloads(root: Path, config: Config) -> dict[str, Literal["sources", "figures", "files"]]:
    """
    Enumerate every current managed payload and reject unregistered encrypted files.

    Args:
        root (Path): Ciphertext checkout or candidate snapshot.
        config (Config): Explicit ownership manifest.

    Returns:
        dict[str, Literal["sources", "figures", "files"]]: Stable envelope paths and authenticated purposes.

    Raises:
        ValueError: A managed file is missing or an extra envelope has no reviewed ownership entry.
    """
    result: dict[str, Literal["sources", "figures", "files"]] = {SOURCE: "sources"}
    if (root / FIGURES).exists():
        result[FIGURES] = "figures"
    result.update({file_path(name): "files" for name in config.managed_files})
    discovered = {str(path.relative_to(root)) for path in (root / "collection").rglob("*.enc.json")}
    if set(result) != discovered:
        raise ValueError("Managed inventory differs; review missing or unregistered encrypted files")
    for path in (root / "collection").rglob("*.enc.json.*"):
        if str(path.relative_to(root)) not in {name + suffix for name in result for suffix in SUFFIXES[1:]}:
            raise ValueError("Orphan encrypted verification file needs review")
    return result


def snapshot(root: Path) -> dict[str, bytes]:
    """
    Capture a bounded complete ciphertext generation without following symlinks.

    Args:
        root (Path): Existing configured collection.

    Returns:
        dict[str, bytes]: Configuration, envelopes and public verification material only.

    Raises:
        ValueError: A file is unsafe, oversized, or missing.
    """
    if (root / ".config").is_symlink() or (root / CONFIG).is_symlink():
        raise ValueError("Trust configuration cannot be a symlink")
    config = load_config(root)
    names = [CONFIG, PUBLIC]
    for relative in payloads(root, config):
        names.extend(relative + suffix for suffix in SUFFIXES)
    if (root / PINS).exists():
        names.append(PINS)
    if (root / RECEIPT).exists():
        names.extend(RECEIPT + suffix for suffix in SUFFIXES)
    result: dict[str, bytes] = {}
    total = 0
    for name in sorted(names):
        path = root / name
        if any(parent.is_symlink() for parent in (path, *path.parents) if parent == root or root in parent.parents):
            raise ValueError("Managed snapshots cannot follow symlinks")
        limit = MAX_BYTES * 2 if name.endswith(".enc.json") else 262144
        if not path.is_file() or path.stat().st_size > limit:
            raise ValueError("Managed file is missing or oversized")
        content = path.read_bytes()
        total += len(content)
        if len(content) > limit or total > 256 * 1024 * 1024:
            raise ValueError("Managed snapshot exceeds the 256 MiB limit")
        result[name] = content
    return result


def recover(root: Path, config: Config, keys: Material, relative: str, purpose: Literal["sources", "figures", "files"]) -> bytes:
    """
    Authenticate the saved ciphertext and recover the exact bytes, including opaque path binding.

    Args:
        root (Path): Immutable snapshot directory.
        config (Config): Independently checked generation pins.
        keys (Material): Existing or candidate decryption identity.
        relative (str): Managed ciphertext path.
        purpose (Literal["sources", "figures", "files"]): Authenticated category.

    Returns:
        bytes: Verified plaintext in memory.

    Raises:
        ValueError: Signature, checksum, key or opaque name binding differs.
    """
    path = root / relative
    verify(path, root / PUBLIC, config)
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != Path(str(path) + ".sha256").read_text().strip():
        raise ValueError("Ciphertext checksum differs")
    plain = decrypt(content, keys.private.encode(), keys.password.encode(), config, purpose)
    if purpose == "files":
        record = structure(json.loads(plain), FileRecord)
        if file_path(record.name) != relative:
            raise ValueError("Opaque file identity differs from the managed path")
        base64.b64decode(record.content, validate=True)
    return plain


def seal_file(checkout: Path, source: Path, directory: Path, name: str, today: date) -> None:
    """
    Explicitly add one arbitrary file without broadening the source archive allowlist.

    Args:
        checkout (Path): Ciphertext collection receiving a reviewed opaque identifier.
        source (Path): Protected local input outside Git.
        directory (Path): Existing private key backup.
        name (str): Non-sensitive identifier visible in the publication manifest.
        today (date): UTC date for write policy.

    Returns:
        None: Signed envelope and configuration are ready for a reviewed Git commit.

    Raises:
        ValueError: Input is unsafe, oversized, or keys do not match.
    """
    relative = file_path(name)
    config_bytes = (checkout / CONFIG).read_bytes()
    config = load_config(checkout)
    deadline_check(config, today)
    require_protected(source)
    if (
        source.is_symlink()
        or not source.is_file()
        or source.resolve().is_relative_to(checkout.resolve())
        or source.stat().st_size > MAX_BYTES // 2
    ):
        raise ValueError("Use a regular protected input outside Git, at most 16 MiB")
    keys = read_keys(directory)
    expected = keys.validate(config.repository)
    if (expected.encryption_fingerprint, expected.signing_fingerprint) != (config.encryption_fingerprint, config.signing_fingerprint):
        raise ValueError("Key backup differs from configured identities")
    if name not in config.managed_files and len(config.managed_files) >= 64:
        raise ValueError("At most 64 opaque files can be managed")
    record = FileRecord(name, base64.b64encode(source.read_bytes()).decode())
    data = (json.dumps(as_data(record), sort_keys=True) + "\n").encode()
    save(
        checkout,
        relative,
        encrypt(data, keys.public.encode(), config, "files"),
        keys.signing_public.encode(),
        config,
        keys.environment(dict(os.environ)),
    )
    updated = evolve(config, managed_files=tuple(sorted(set((*config.managed_files, name)))))
    replace_file(checkout / CONFIG, (json.dumps(as_data(updated), indent=2) + "\n").encode(), expected=config_bytes)


def restore_file(checkout: Path, directory: Path, name: str, output: Path) -> None:
    """
    Restore an explicitly managed file into a new protected destination without publishing it.

    Args:
        checkout (Path): Current or retained encrypted snapshot.
        directory (Path): Matching retained key backup.
        name (str): Previously registered opaque identifier.
        output (Path): New protected path outside Git.

    Returns:
        None: Verified original file bytes are written with private permissions.
    """
    require_protected(output)
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(checkout.resolve()):
        raise ValueError("Restore to a new protected file outside Git")
    config = load_config(checkout)
    if name not in config.managed_files:
        raise ValueError("File is not managed by this collection")
    keys = read_keys(directory)
    if keys.validate(config.repository).signing_fingerprint != config.signing_fingerprint:
        raise ValueError("Retained signing identity differs")
    record = structure(json.loads(recover(checkout, config, keys, file_path(name), "files")), FileRecord)
    replace_file(output, base64.b64decode(record.content, validate=True), expected=None)
