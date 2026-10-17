"""
Seal local records, restore authenticated snapshots, and rebuild only from current encrypted inputs.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from witful.checkpoints.journal import read as read_checkpoints
from witful.checkpoints.plotting import build as checkpoint_plots
from witful.collection import archive
from witful.collection.crypto import decrypt, encrypt, fingerprint, save, verify
from witful.collection.dashboard import FIGURES as FIGURE_CATALOG
from witful.collection.dashboard import readme as readme
from witful.collection.keys import signing_environment
from witful.collection.managed import deadline_check
from witful.collection.models import FIGURES, SOURCE, load_config
from witful.collection.process import private_repository
from witful.collection.protection import require_protected
from witful.files import replace_file
from witful.instances.reporting import build as instance_plots
from witful.knowledge.applications import read_applications
from witful.knowledge.compiler import compile_identity
from witful.knowledge.contracts import structure
from witful.knowledge.models import Catalog
from witful.knowledge.plotting import write_plots as knowledge_plots
from witful.lessons import read_journal
from witful.life.journal import read_archive
from witful.life.plotting import write_influences
from witful.life.replay import render as life_plots
from witful.privacy.scanner import scan_text
from witful.reflection.journal import config as reflection_config
from witful.reflection.journal import read as read_reviews
from witful.reflection.planning import plan as reflection_plan
from witful.reflection.plotting import FIGURES as REVIEW_FIGURES
from witful.reflection.plotting import build as reflection_plots
from witful.repertoire.models import Inventory, Use
from witful.repertoire.plotting import write_plots as repertoire_plots


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
    deadline_check(config, datetime.now(UTC).date())
    private_repository(config.repository)

    if source.resolve().is_relative_to(checkout.resolve()) or keys.resolve().is_relative_to(checkout.resolve()):
        raise ValueError("Plaintext sources and key backups must stay outside the Git checkout")

    require_protected(source)
    require_protected(keys)
    archive.validate(source)
    payload = encrypt(archive.pack(source), (keys / "collection.pub").read_bytes(), config, "sources")
    save(checkout, SOURCE, payload, (keys / "cosign.pub").read_bytes(), config, signing_environment(keys))


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

    require_protected(output)
    require_protected(keys)
    config = load_config(checkout)
    path = checkout / (SOURCE if purpose == "sources" else FIGURES)
    if fingerprint((keys / "cosign.pub").read_bytes()) != config.signing_fingerprint:
        raise ValueError("Local signing identity differs from the downloaded trust configuration")
    verify(path, checkout / "collection/cosign.pub", config)
    data = decrypt(path.read_bytes(), (keys / "collection.key").read_bytes(), (keys / "collection.password").read_bytes(), config, purpose)
    archive.unpack(data, output, figures=purpose == "figures")
    if purpose == "sources":
        replace_file(output / ".witful-protected", b"encrypted-working-storage-v1\n", expected=None)


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
    instance_plots(root, destination)

    decisions = read_archive(root)
    life_plots(decisions, root, destination)
    write_influences(decisions, destination)
    if reflection_config(root).enabled:
        latest = {item.decision_id: item for event in read_reviews(root) for item in event.assessments}
        reflection_plots(tuple(latest[key] for key in sorted(latest)), destination)


def refresh(checkout: Path, environment: dict[str, str] | None = None, *, history: Path | None = None) -> None:
    """
    Run the trusted main-branch refresh while retaining plaintext only in temporary local storage.

    Args:
        checkout (Path): Verified private repository checkout.
        environment (dict[str, str] | None): Explicit selected key generation, or the current process environment.
        history (Path | None): Original full Git checkout for review cadence; defaults to checkout for direct refreshes.

    Returns:
        None: Encrypted figures and a generated README replace prior outputs after full validation.

    Raises:
        ValueError: Event identity, repository visibility, trust pins, or source validation fail.
    """
    env = dict(os.environ) if environment is None else environment
    config = load_config(checkout)
    deadline_check(config, datetime.now(UTC).date())

    if (
        env.get("GITHUB_REPOSITORY", "").lower() != config.repository.lower()
        or env.get("GITHUB_EVENT_NAME") not in {"push", "workflow_dispatch"}
        or env.get("GITHUB_REF") != "refs/heads/main"
    ):
        raise ValueError("Collection refresh is restricted to the configured private main branch")

    private_repository(config.repository)
    if config.signing_fingerprint != env["WITFUL_COLLECTION_SIGNING_FINGERPRINT"]:
        raise ValueError("Downloaded signing configuration differs from the independent Actions trust pin")
    path = checkout / SOURCE
    verify(path, checkout / "collection/cosign.pub", config)
    public = env["WITFUL_COLLECTION_PUBLIC_KEY"].encode()

    if fingerprint(public) != config.encryption_fingerprint:
        raise ValueError("CI encryption secret differs from the configured recipient")

    # The CI launcher supplies a nonswappable memory filesystem; never fall back to runner disk.
    temporary_root = Path(env["WITFUL_SECURE_TEMP"])
    require_protected(temporary_root)
    data = decrypt(
        path.read_bytes(),
        env["WITFUL_COLLECTION_PRIVATE_KEY"].encode(),
        env["WITFUL_COLLECTION_KEY_PASSWORD"].encode(),
        config,
        "sources",
    )

    # This tree is never cached or uploaded. Exit, validation failure, and ordinary cancellation remove it.
    with TemporaryDirectory(prefix="witful-plain-", dir=temporary_root) as temporary:
        root, figures = Path(temporary) / "sources", Path(temporary) / "figures"
        archive.unpack(data, root)
        render(root, figures)
        review_settings = reflection_config(root)
        if review_settings.enabled:
            # The plan contains private decision text and travels only inside the signed encrypted figure archive.
            plan = reflection_plan(root, checkout if history is None else history)
            (figures / "reflection-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
            print(json.dumps({"reflection_due": plan["due"], "review_decisions": plan["decision_count"]}))
        (figures / "provenance.json").write_text(
            json.dumps(
                {
                    "source_ciphertext_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "source_commit": env.get("GITHUB_SHA", ""),
                    "repository": config.repository,
                },
                sort_keys=True,
            )
            + "\n"
        )
        encrypted = encrypt(archive.pack(figures, figures=True), public, config, "figures")
        save(checkout, FIGURES, encrypted, (checkout / "collection/cosign.pub").read_bytes(), config, dict(env))

        # Readable plots are a separate explicit disclosure. Scan vector labels before placing them in Git.
        readable = checkout / "docs/collection"

        figure_ids = tuple(name for name in FIGURE_CATALOG if review_settings.enabled or name not in REVIEW_FIGURES)
        if config.publish_figures:
            for identifier in figure_ids:
                content = (figures / f"{identifier}.svg").read_text()

                if scan_text(content):
                    raise ValueError("Readable figure contains a detected personal-data pattern; keep figures encrypted or revise labels")

            readable.mkdir(parents=True, exist_ok=True)

            for identifier in figure_ids:
                (readable / f"{identifier}.svg").write_bytes((figures / f"{identifier}.svg").read_bytes())
            if not review_settings.enabled:
                for identifier in REVIEW_FIGURES:
                    (readable / f"{identifier}.svg").unlink(missing_ok=True)
        elif readable.exists():
            for identifier in FIGURE_CATALOG:
                (readable / f"{identifier}.svg").unlink(missing_ok=True)

    dashboard = readme(config, hashlib.sha256(path.read_bytes()).hexdigest(), reflection_enabled=review_settings.enabled).encode()
    target = checkout / "README.md"
    replace_file(target, dashboard, expected=target.read_bytes() if target.exists() else None)
