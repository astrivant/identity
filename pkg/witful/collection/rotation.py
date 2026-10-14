"""
Prepare recoverable key transitions without mutating the active collection or retained history.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import TYPE_CHECKING

from attrs import evolve

from witful.collection.crypto import encrypt, fingerprint, save, verify
from witful.collection.managed import PINS, PUBLIC, RECEIPT, SUFFIXES, deadline_check, payloads, recover, snapshot
from witful.collection.material import Candidate, Material, read_candidate
from witful.collection.models import CONFIG, Config, load_config
from witful.files import replace_file
from witful.knowledge.contracts import as_data

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date
    from pathlib import Path


def write_snapshot(root: Path, contents: Mapping[str, bytes]) -> None:
    """
    Materialize only ciphertext and public metadata into a new snapshot directory.

    Args:
        root (Path): New output, never a live checkout.
        contents (Mapping[str, bytes]): Internally validated relative paths and immutable bytes.

    Returns:
        None: A recoverable snapshot exists with restrictive permissions.
    """
    root.mkdir(mode=0o700)
    for name, data in contents.items():
        replace_file(root / name, data, expected=None)


def trusted(config: Config, keys: Material) -> None:
    """
    Require independently supplied key material to match both active pins.

    Args:
        config (Config): Configuration from the collection under inspection.
        keys (Material): Independently retained or secret-projected keys.

    Returns:
        None: Both pairs match the configured generation.

    Raises:
        ValueError: Either encryption or signing identity differs.
    """
    expected = keys.validate(config.repository)
    if (expected.encryption_fingerprint, expected.signing_fingerprint) != (config.encryption_fingerprint, config.signing_fingerprint):
        raise ValueError("Independent keys differ from the configured generation")


def rotate(checkout: Path, current: Material, candidate: Candidate, output: Path, today: date, source_commit: str = "") -> Path:
    """
    Verify backup restoration and prepare all replacements as one reviewable generation.

    Args:
        checkout (Path): Current encrypted collection, left unchanged even on failure.
        current (Material): Independently retained old keys.
        candidate (Candidate): Complete new key set and future rotation deadline.
        output (Path): New directory outside the checkout for previous/current snapshots.
        today (date): Explicit UTC policy clock.
        source_commit (str): Optional authoritative source revision, never inferred from file contents.

    Returns:
        Path: New current snapshot, ready for atomic Git publication alongside its trust configuration.

    Raises:
        ValueError: Keys, inventory, backup, signatures, deadline, or round-trip recovery differ.
        RuntimeError: Current inputs changed during preparation.
    """
    before = snapshot(checkout)
    old = load_config(checkout)
    trusted(old, current)
    if candidate.repository != old.repository:
        raise ValueError("Candidate belongs to another repository")
    proposed = candidate.keys.validate(old.repository)
    new = evolve(
        old,
        encryption_fingerprint=proposed.encryption_fingerprint,
        signing_fingerprint=proposed.signing_fingerprint,
        rotate_by=candidate.rotate_by,
    )
    deadline_check(new, today)
    # This policy date belongs to the whole generation; retaining either key must not reset its lifetime.
    if old.encryption_fingerprint == new.encryption_fingerprint or old.signing_fingerprint == new.signing_fingerprint:
        raise ValueError("Replace both keys before establishing a new generation deadline")
    if output.resolve().is_relative_to(checkout.resolve()) or output.exists() or output.is_symlink():
        raise ValueError("Choose a new rotation output outside the active checkout")
    output.mkdir(mode=0o700, parents=True)
    previous, replacement = output / "previous", output / "current"
    write_snapshot(previous, before)

    # Authenticate and restore every old payload from the backup itself before preparing any replacements.
    inventory = payloads(previous, old)
    verify_snapshot(previous, current)
    write_snapshot(
        replacement, {CONFIG: (json.dumps(as_data(new), indent=2) + "\n").encode(), PUBLIC: candidate.keys.signing_public.encode()}
    )
    env = candidate.keys.environment(dict(os.environ))
    for relative, purpose in inventory.items():
        plain = recover(previous, old, current, relative, purpose)
        encrypted = encrypt(plain, candidate.keys.public.encode(), new, purpose)
        save(replacement, relative, encrypted, candidate.keys.signing_public.encode(), new, env)
        if recover(replacement, new, candidate.keys, relative, purpose) != plain:
            raise ValueError("Candidate restoration differs from the verified backup")

    replace_file(
        replacement / PINS,
        (json.dumps({"encryption": new.encryption_fingerprint, "signing": new.signing_fingerprint}, indent=2) + "\n").encode(),
        expected=None,
    )
    after = snapshot(replacement)
    receipt = (
        json.dumps(
            {
                "version": 1,
                "repository": old.repository,
                "source_commit": source_commit,
                "previous_encryption": old.encryption_fingerprint,
                "previous_signing": old.signing_fingerprint,
                "encryption": new.encryption_fingerprint,
                "signing": new.signing_fingerprint,
                "rotate_by": new.rotate_by,
                "history_policy": "retain-old-keys",
                "previous": {name: hashlib.sha256(data).hexdigest() for name, data in before.items()},
                "current": {name: hashlib.sha256(data).hexdigest() for name, data in after.items()},
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode()

    # The same transition is authenticated by both generations; it contains only public pins and ciphertext digests.
    save(replacement, RECEIPT, receipt, candidate.keys.signing_public.encode(), new, env)
    save(previous, "collection/next-rotation.json", receipt, current.signing_public.encode(), old, current.environment(dict(os.environ)))
    if snapshot(checkout) != before:
        raise RuntimeError("Collection changed during rotation; discard the candidate and prepare from current inputs")
    replace_file(output / "READY", hashlib.sha256(receipt).hexdigest().encode() + b"\n", expected=None)
    return replacement


def select_keys(checkout: Path, env: dict[str, str], today: date) -> tuple[Material, Candidate | None]:
    """
    Select one coherent active generation without silently ignoring invalid candidate secrets.

    Args:
        checkout (Path): Trusted private main checkout.
        env (dict[str, str]): Secrets supplied only after trusted-event and visibility checks.
        today (date): Explicit UTC policy clock.

    Returns:
        tuple[Material, Candidate | None]: Active keys and an optional unadopted candidate.

    Raises:
        ValueError: Active trust pins differ, or a requested candidate is invalid or mixed.
    """
    config = load_config(checkout)
    value = env.get("WITFUL_COLLECTION_NEXT_KEYS", "")
    candidate = read_candidate(value, config.repository, today) if value else None
    if candidate is not None:
        proposed = candidate.keys.validate(config.repository)
        if (proposed.encryption_fingerprint, proposed.signing_fingerprint) == (config.encryption_fingerprint, config.signing_fingerprint):
            if candidate.rotate_by != config.rotate_by:
                raise ValueError("An adopted candidate cannot silently extend its rotation deadline")
            trusted(config, candidate.keys)
            return candidate.keys, None

    public = (checkout / PUBLIC).read_text()
    if fingerprint(public.encode()) != env["WITFUL_COLLECTION_SIGNING_FINGERPRINT"]:
        raise ValueError("Downloaded signing key differs from the independent Actions trust pin")
    active = Material(
        env["WITFUL_COLLECTION_PRIVATE_KEY"],
        env["WITFUL_COLLECTION_PUBLIC_KEY"],
        env["WITFUL_COLLECTION_KEY_PASSWORD"],
        env["COSIGN_PRIVATE_KEY"],
        public,
        env["COSIGN_PASSWORD"],
    )
    trusted(config, active)
    return active, candidate


def verify_snapshot(root: Path, keys: Material) -> None:
    """
    Verify the complete managed generation before publication, including additional files and receipts.

    Args:
        root (Path): Current prepared ciphertext snapshot.
        keys (Material): Independently trusted active generation.

    Returns:
        None: Every owned payload restores and any transition receipt verifies.
    """
    snapshot(root)
    config = load_config(root)
    trusted(config, keys)
    for relative, purpose in payloads(root, config).items():
        recover(root, config, keys, relative, purpose)
    if (root / RECEIPT).exists():
        verify(root / RECEIPT, root / PUBLIC, config)
        if hashlib.sha256((root / RECEIPT).read_bytes()).hexdigest() != (root / (RECEIPT + SUFFIXES[2])).read_text().strip():
            raise ValueError("Transition receipt checksum differs")
