"""
Seal local records, restore authenticated snapshots, and rebuild only from current encrypted inputs.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Literal

from witful.awareness.models import FIGURES as FIGURE_CATALOG
from witful.checkpoints.journal import read as read_checkpoints
from witful.checkpoints.plotting import build as checkpoint_plots
from witful.collection import archive
from witful.collection.crypto import decrypt, encrypt, fingerprint, sign, verify
from witful.collection.keys import signing_environment
from witful.collection.models import FIGURES, SOURCE, load_config
from witful.collection.process import private_repository
from witful.files import replace_file
from witful.knowledge.applications import read_applications
from witful.knowledge.compiler import compile_identity
from witful.knowledge.contracts import structure
from witful.knowledge.models import Catalog
from witful.knowledge.plotting import write_plots as knowledge_plots
from witful.lessons import read_journal
from witful.privacy.scanner import scan_text
from witful.repertoire.models import Inventory, Use
from witful.repertoire.plotting import write_plots as repertoire_plots

if TYPE_CHECKING:
    from witful.collection.models import Config


def _save(root: Path, relative: str, content: bytes, public: bytes, config: Config, env: dict[str, str]) -> None:
    """
    Finalize and verify ciphertext before replacing the committed envelope and verification set.

    Args:
        root (Path): Repository checkout receiving opaque files.
        relative (str): Fixed output path.
        content (bytes): Canonical encrypted bytes.
        public (bytes): Cosign verification key.
        config (Config): Independently trusted key fingerprints.
        env (dict[str, str]): Scoped signing environment.

    Returns:
        None: Verified ciphertext, signature, and checksum are written without plaintext staging.
    """
    with TemporaryDirectory(prefix="witful-seal-") as temporary:
        staged = Path(temporary) / "payload.json"
        staged.write_bytes(content)
        verification = Path(temporary) / "cosign.pub"
        verification.write_bytes(public)
        sign(staged, env)
        verify(staged, verification, config)
        outputs = {
            relative: content,
            relative + ".sigstore.json": Path(str(staged) + ".sigstore.json").read_bytes(),
            relative + ".sha256": (hashlib.sha256(content).hexdigest() + "\n").encode(),
        }

        for name, data in outputs.items():
            path = root / name
            replace_file(path, data, expected=path.read_bytes() if path.exists() else None)


def seal(checkout: Path, source: Path, keys: Path) -> None:
    """
    Validate and encrypt the latest local source collection for a private repository push.

    Args:
        checkout (Path): Private repository owning its trust configuration.
        source (Path): Local plaintext collection outside the checkout.
        keys (Path): Dedicated local key backup.

    Returns:
        None: Only the encrypted source and its signature/checksum change in the checkout.
    """
    config = load_config(checkout)
    private_repository(config.repository)

    if source.resolve().is_relative_to(checkout.resolve()) or keys.resolve().is_relative_to(checkout.resolve()):
        raise ValueError("Plaintext sources and key backups must stay outside the Git checkout")

    archive.validate(source)
    payload = encrypt(archive.pack(source), (keys / "collection.pub").read_bytes(), config, "sources")
    _save(checkout, SOURCE, payload, (keys / "cosign.pub").read_bytes(), config, signing_environment(keys))


def restore(checkout: Path, keys: Path, output: Path, purpose: Literal["sources", "figures"]) -> None:
    """
    Verify and decrypt into a new local directory without contacting GitHub.

    Args:
        checkout (Path): Downloaded collection and independent trust pins.
        keys (Path): Saved RSA decryption key and password.
        output (Path): New destination outside the Git checkout.
        purpose (Literal["sources", "figures"]): Select sources or the generated figure archive.

    Returns:
        None: Authenticated files are restored without replacing an active collection.
    """
    if output.resolve().is_relative_to(checkout.resolve()):
        raise ValueError("Restore private data outside the repository checkout")

    config = load_config(checkout)
    path = checkout / (SOURCE if purpose == "sources" else FIGURES)
    verify(path, checkout / "collection/cosign.pub", config)
    data = decrypt(path.read_bytes(), (keys / "collection.key").read_bytes(), (keys / "collection.password").read_bytes(), config, purpose)
    archive.unpack(data, output, figures=purpose == "figures")


def render(root: Path, destination: Path) -> None:
    """
    Derive all supported views from validated sources, including honest empty-state figures.

    Args:
        root (Path): Decrypted source tree.
        destination (Path): Temporary render directory.

    Returns:
        None: Current knowledge, repertoire, and checkpoint figures are generated.
    """
    archive.validate(root)
    catalog = structure(json.loads((root / "knowledge/catalog.json").read_text()), Catalog)
    identity = compile_identity(read_journal(root / "lessons.jsonl"), catalog)
    knowledge_plots(identity, read_applications(root / "knowledge/applications.jsonl"), destination)
    inventory_path = root / "knowledge/repertoire.json"
    inventory = structure(json.loads(inventory_path.read_text()), Inventory) if inventory_path.exists() else Inventory()
    journal = root / "knowledge/tool-uses.jsonl"
    events = [structure(json.loads(line), Use) for line in (journal.read_text() if journal.exists() else "").splitlines()]
    repertoire_plots(inventory, events, destination)
    checkpoint_plots(read_checkpoints(root / "knowledge/checkpoints.jsonl"), destination)


def readme(config: Config, source_digest: str) -> str:
    """
    Replace library onboarding with the owner's private collection dashboard.

    Args:
        config (Config): Reviewed publication choices.
        source_digest (str): SHA-256 of ciphertext, never plaintext or private labels.

    Returns:
        str: Repository-specific README with no source records or inferred personal metadata.
    """
    repository = config.repository
    text = (
        "# My knowledge collection\n\n"
        f"[![CI](https://github.com/{repository}/actions/workflows/ci.yml/badge.svg)]"
        f"(https://github.com/{repository}/actions/workflows/ci.yml)\n\n"
        "Sourced lessons, observed applications, and project checkpoints managed with "
        "[Witful](https://github.com/astrivant/identity).\n\n"
        "<!-- toc:start -->\n**Table of contents**\n\n- [Current figures](#current-figures)\n"
        "- [Update](#update)\n<!-- toc:end -->\n\n## Current figures\n\n"
        f"Rebuilt from encrypted source SHA-256 `{source_digest}`.\n\n"
    )

    if config.publish_figures:
        for identifier, (_, title) in FIGURE_CATALOG.items():
            text += f"![{title}](docs/collection/{identifier}.svg)\n\n"
    else:
        text += (
            "Full figures are encrypted in `collection/figures.enc.json`. "
            "GitHub cannot display encrypted images inline. Restore them locally with "
            "`witful collection restore --checkout CHECKOUT --key-dir KEYS --output NEW_DIRECTORY --figures`.\n\n"
        )

    return text + (
        "## Update\n\nUse `witful collection seal --checkout CHECKOUT --source COLLECTION --key-dir KEYS`, "
        "then commit the named encrypted outputs and push. Main CI refreshes this README and the figures.\n\n"
        "See [private collection setup](docs/private-collections.md) for installation, recovery, "
        "verification, and the optional readable-figure setting.\n"
    )


def refresh(checkout: Path) -> None:
    """
    Run the trusted main-branch refresh while retaining plaintext only in temporary local storage.

    Args:
        checkout (Path): Verified private repository checkout.

    Returns:
        None: Encrypted figures and a generated README replace prior outputs after full validation.

    Raises:
        ValueError: Event identity, repository visibility, trust pins, or source validation fail.
    """
    config = load_config(checkout)

    if (
        os.environ.get("GITHUB_REPOSITORY", "").lower() != config.repository.lower()
        or os.environ.get("GITHUB_EVENT_NAME") not in {"push", "workflow_dispatch"}
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
    ):
        raise ValueError("Collection refresh is restricted to the configured private main branch")

    private_repository(config.repository)
    path = checkout / SOURCE
    verify(path, checkout / "collection/cosign.pub", config)
    public = os.environ["WITFUL_COLLECTION_PUBLIC_KEY"].encode()

    if fingerprint(public) != config.encryption_fingerprint:
        raise ValueError("CI encryption secret differs from the configured recipient")

    data = decrypt(
        path.read_bytes(),
        os.environ["WITFUL_COLLECTION_PRIVATE_KEY"].encode(),
        os.environ["WITFUL_COLLECTION_KEY_PASSWORD"].encode(),
        config,
        "sources",
    )

    # This tree is never cached or uploaded. Exit, validation failure, and ordinary cancellation remove it.
    with TemporaryDirectory(prefix="witful-plain-", dir=os.environ.get("RUNNER_TEMP")) as temporary:
        root, figures = Path(temporary) / "sources", Path(temporary) / "figures"
        archive.unpack(data, root)
        render(root, figures)
        (figures / "provenance.json").write_text(
            json.dumps(
                {
                    "source_ciphertext_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "source_commit": os.environ.get("GITHUB_SHA", ""),
                    "repository": config.repository,
                },
                sort_keys=True,
            )
            + "\n"
        )
        encrypted = encrypt(archive.pack(figures, figures=True), public, config, "figures")
        _save(checkout, FIGURES, encrypted, (checkout / "collection/cosign.pub").read_bytes(), config, dict(os.environ))

        # Readable plots are a separate explicit disclosure. Scan vector labels before placing them in Git.
        readable = checkout / "docs/collection"

        if config.publish_figures:
            for identifier in FIGURE_CATALOG:
                content = (figures / f"{identifier}.svg").read_text()

                if scan_text(content):
                    raise ValueError("Readable figure contains a detected personal-data pattern; keep figures encrypted or revise labels")

            readable.mkdir(parents=True, exist_ok=True)

            for identifier in FIGURE_CATALOG:
                (readable / f"{identifier}.svg").write_bytes((figures / f"{identifier}.svg").read_bytes())
        elif readable.exists():
            for identifier in FIGURE_CATALOG:
                (readable / f"{identifier}.svg").unlink(missing_ok=True)

    dashboard = readme(config, hashlib.sha256(path.read_bytes()).hexdigest()).encode()
    target = checkout / "README.md"
    replace_file(target, dashboard, expected=target.read_bytes() if target.exists() else None)
