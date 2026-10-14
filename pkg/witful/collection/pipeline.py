"""
Prepare a complete private publication candidate before any Git ref or secret changes.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from witful.collection import archive
from witful.collection.managed import deadline_check, snapshot
from witful.collection.models import load_config
from witful.collection.operations import refresh
from witful.collection.process import private_repository, run
from witful.collection.protection import require_protected
from witful.collection.publication import publication_files
from witful.collection.rotation import rotate, select_keys, verify_snapshot, write_snapshot
from witful.files import replace_file

if TYPE_CHECKING:
    from datetime import date
    from pathlib import Path


def authorize(checkout: Path, env: dict[str, str]) -> None:
    """
    Reject untrusted events and tracked plaintext before reading candidate credentials.

    Args:
        checkout (Path): Current repository checkout.
        env (dict[str, str]): GitHub-provided immutable run context.

    Returns:
        None: The configured private main checkout may process protected inputs.

    Raises:
        ValueError: Event scope, repository visibility, or the publication boundary differs.
    """
    config = load_config(checkout)
    if (
        env.get("GITHUB_REPOSITORY", "").lower() != config.repository.lower()
        or env.get("GITHUB_EVENT_NAME") not in {"push", "workflow_dispatch"}
        or env.get("GITHUB_REF") != "refs/heads/main"
    ):
        raise ValueError("Collection rotation is restricted to the configured private main branch")
    private_repository(config.repository)
    if run(["git", "rev-parse", "HEAD"], cwd=checkout).decode().strip() != env["GITHUB_SHA"]:
        raise ValueError("Checkout differs from the immutable workflow source")
    tracked = run(["git", "ls-files", "-z"], cwd=checkout).decode().split("\0")
    if any(
        archive.allowed(name) or (name.startswith("knowledge/") and name.endswith(".jsonl")) or ".sqlite" in name
        for name in tracked
        if name
    ):
        raise ValueError("Plaintext source records or indexes remain tracked")


def prepare(checkout: Path, output: Path, env: dict[str, str], today: date) -> Path:
    """
    Rotate on a pending candidate, otherwise refresh with the selected active generation.

    Args:
        checkout (Path): Unchanged trusted main source checkout.
        output (Path): New protected output directory, separate from source and key backups.
        env (dict[str, str]): Existing secrets plus optional WITFUL_COLLECTION_NEXT_KEYS.
        today (date): Explicit UTC policy clock.

    Returns:
        Path: Fully verified publication directory; previous ciphertext is retained separately on rotation.

    Raises:
        ValueError: Input, credentials, protection, or complete candidate verification fails.
        RuntimeError: Inputs changed before candidate finalization.
    """
    authorize(checkout, env)
    require_protected(output)
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(checkout.resolve()):
        raise ValueError("Prepare into a new protected directory outside the checkout")
    before = snapshot(checkout)
    keys, candidate = select_keys(checkout, env, today)
    if candidate is not None:
        current = rotate(checkout, keys, candidate, output, today, env["GITHUB_SHA"])
        keys = candidate.keys
        # Retain the exact decrypt-compared generation before regenerating figures from current sources.
        write_snapshot(output / "rotated", snapshot(current))
    else:
        deadline_check(load_config(checkout), today)
        output.mkdir(mode=0o700, parents=True)
        current = output / "current"
        write_snapshot(current, before)
    # Prepared ciphertext has no Git metadata; cadence must use the authorized source checkout.
    refresh(current, keys.environment(env), history=checkout)
    verify_snapshot(current, keys)
    if snapshot(checkout) != before:
        raise RuntimeError("Source changed during preparation; rerun against current main")
    # Publication requires this final marker. A partial directory is never a valid candidate.
    contents = publication_files(current)
    manifest = {"source_commit": env["GITHUB_SHA"], "files": {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}}
    replace_file(output / "VERIFIED", (json.dumps(manifest, sort_keys=True) + "\n").encode(), expected=None)
    return current
