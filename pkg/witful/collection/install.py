"""
Install a private collection beside existing Codex settings and configure explicit GitHub ownership.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from importlib.resources import files
from typing import TYPE_CHECKING

from witful.collection.crypto import fingerprint
from witful.collection.keys import prepare, project
from witful.collection.models import CONFIG, load_config
from witful.collection.operations import restore, seal
from witful.collection.process import private_repository, run
from witful.collection.protection import require_protected
from witful.files import replace_file
from witful.knowledge.contracts import as_data
from witful.project import main as initialize

if TYPE_CHECKING:
    from pathlib import Path


def setup(repository: str, checkout: Path, home: Path, keys: Path, *, create: bool = False, restore_existing: bool = False) -> None:
    """
    Initialize local state, preserve preferences, and enable the private pipeline after secrets exist.

    Args:
        repository (str): Explicit destination owner/repository on GitHub.com.
        checkout (Path): Existing clone of the public library or the selected private copy.
        home (Path): Codex home; existing settings and authentication remain untouched.
        keys (Path): Dedicated encryption/signing backup outside both source trees.
        create (bool): Explicitly authorize creating an independent private GitHub copy from this clone.
        restore_existing (bool): Recover an existing encrypted collection into a new local home directory.

    Returns:
        None: Local collection, skill, trust pins, encrypted seed, and Actions secrets are configured.

    Raises:
        ValueError: Repository scope, existing data, key identity, or access prevents safe setup.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", repository) or repository.lower() == "astrivant/identity":
        raise ValueError("Select your own explicit owner/repository")

    if any(shutil.which(tool) is None for tool in ("git", "gh", "ssh-keygen", "openssl", "cosign")):
        raise ValueError("Install Git, gh, OpenSSH, OpenSSL, and Cosign before setup")

    checkout, home, keys = checkout.resolve(), home.expanduser().resolve(), keys.expanduser().resolve()
    source = home / "collection"

    if home.is_relative_to(checkout) or keys.is_relative_to(checkout) or keys.is_relative_to(source):
        raise ValueError("Codex home and key backups must stay outside the repository checkout")

    # Verify all persistent private working paths before keys, sources, or remote setup changes.
    require_protected(home)
    require_protected(keys)

    origin = run(["git", "remote", "get-url", "origin"], cwd=checkout).decode().strip().removesuffix(".git")
    expected = {f"git@github.com:{repository}", f"https://github.com/{repository}"}

    if origin not in expected:
        if not create or origin not in {"git@github.com:astrivant/identity", "https://github.com/astrivant/identity"}:
            raise ValueError("Checkout origin must match --repo; use --create only in a fresh clone of the public library")

        # Create without pushing. A failure leaves recoverable local state and never publishes unencrypted records.
        run(["gh", "repo", "create", repository, "--private"])
        run(["git", "remote", "rename", "origin", "upstream"], cwd=checkout)
        run(["git", "remote", "add", "origin", f"git@github.com:{repository}.git"], cwd=checkout)

    private_repository(repository)
    config_path = checkout / CONFIG
    previous = load_config(checkout) if config_path.exists() else None

    # An existing seed requires explicit recovery, never replacing a remote collection with an empty one.
    if not source.exists():
        if (checkout / "collection/sources.enc.json").exists():
            if not restore_existing:
                raise ValueError("Use --restore with the original key backup to recover this collection before setup")
            restore(checkout, keys, source, "sources")
        elif restore_existing:
            raise ValueError("No encrypted source snapshot exists to restore")
        else:
            initialize([str(source)])
        (source / ".gitignore").write_text("*\n")

    replace_file(
        source / ".witful-protected",
        b"encrypted-working-storage-v1\n",
        expected=(source / ".witful-protected").read_bytes() if (source / ".witful-protected").exists() else None,
    )

    archive_skill = files("witful.collection").joinpath("resources/SKILL.md").read_bytes()
    target_skill = home / "skills/witful-collection/SKILL.md"

    if target_skill.exists() and target_skill.read_bytes() != archive_skill:
        raise ValueError("An existing collection skill differs; review it before replacing the installed skill")

    config = prepare(keys, repository)

    if previous is not None:
        if previous.repository.lower() != repository.lower() or (previous.encryption_fingerprint, previous.signing_fingerprint) != (
            config.encryption_fingerprint,
            config.signing_fingerprint,
        ):
            raise ValueError("Setup cannot rotate a configured collection's keys; reuse the original backup")
        config = previous

    config_path.parent.mkdir(parents=True, exist_ok=True)
    replace_file(
        config_path, (json.dumps(as_data(config), indent=2) + "\n").encode(), expected=config_path.read_bytes() if previous else None
    )
    public = checkout / "collection/cosign.pub"
    public.parent.mkdir(parents=True, exist_ok=True)
    (public.parent / ".gitignore").write_bytes(files("witful.collection").joinpath("resources/collection.gitignore").read_bytes())
    public.write_bytes((keys / "cosign.pub").read_bytes())
    (public.parent / "key-fingerprints.json").write_text(
        json.dumps(
            {
                "encryption": config.encryption_fingerprint,
                "signing": fingerprint(public.read_bytes()),
            },
            indent=2,
        )
        + "\n"
    )
    seal(checkout, source, keys)
    replace_file(target_skill, archive_skill, expected=target_skill.read_bytes() if target_skill.exists() else None)

    receipt = source / ".setup.json"
    replace_file(
        receipt,
        (
            json.dumps(
                {
                    "repository": repository,
                    "checkout": str(checkout),
                    "keys": str(keys),
                    "command": os.path.join(os.path.dirname(sys.executable), "witful"),
                },
                indent=2,
            )
            + "\n"
        ).encode(),
        expected=receipt.read_bytes() if receipt.exists() else None,
    )

    # A Settings app must not apply upstream public visibility to the new private copy.
    settings = checkout / ".github/settings.yml"

    if settings.exists():
        content = settings.read_text().replace("  private: false", "  private: true")
        content = re.sub(r"(?m)^  name: identity$", f"  name: {repository.split('/')[1]}", content)
        replace_file(settings, content.encode(), expected=settings.read_bytes())

    project(keys, repository)
    run(["gh", "variable", "set", "WITFUL_COLLECTION_ENABLED", "--repo", repository, "--body", "true"])
    print("Setup complete. Commit .config/collection.json, collection/, and .github/settings.yml; then push main.")
