"""
Expose explicit local installation, encrypted publication, restoration, and trusted CI refresh.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidTag, UnsupportedAlgorithm
from jsonschema import ValidationError

from witful.collection import archive, export_cli
from witful.collection.crypto import verify
from witful.collection.exports import Manifest
from witful.collection.install import setup
from witful.collection.keys import project as project_keys
from witful.collection.managed import restore_file, seal_file, snapshot
from witful.collection.material import export_candidate, read_candidate, read_keys
from witful.collection.models import CONFIG, FIGURES, SOURCE, Config, Envelope, load_config
from witful.collection.operations import refresh, restore, seal
from witful.collection.pipeline import prepare as prepare_refresh
from witful.collection.process import private_repository, run
from witful.collection.protection import require_protected
from witful.collection.publication import publish
from witful.collection.rotation import rotate, verify_snapshot
from witful.exceptions import StorageProtectionError
from witful.knowledge.contracts import schema

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run one bounded operation and redact errors that may contain private source values.

    Args:
        argv (Sequence[str] | None): Explicit arguments or process arguments.

    Returns:
        int: Zero on success; two for failed validation, cryptography, tooling, or I/O.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("setup", help="Install into Codex home and project secrets to an explicit private repository")
    install.add_argument("--repo", required=True)
    install.add_argument("--checkout", type=Path, default=Path.cwd())
    install.add_argument("--home", type=Path, default=Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser())
    install.add_argument("--key-dir", type=Path)
    install.add_argument(
        "--restore", action="store_true", help="Restore the encrypted collection into an empty local home using saved keys"
    )
    install.add_argument("--create", action="store_true", help="Create an independent private GitHub repository from a fresh library clone")
    sealing = commands.add_parser("seal", help="Validate, encrypt, and sign the current source collection; Git publication is separate")
    sealing.add_argument("--checkout", type=Path, required=True)
    sealing.add_argument("--source", type=Path, required=True)
    sealing.add_argument("--key-dir", type=Path, required=True)
    restoring = commands.add_parser("restore", help="Verify then decrypt sources or figures into a new local directory")
    restoring.add_argument("--checkout", type=Path, required=True)
    restoring.add_argument("--key-dir", type=Path, required=True)
    restoring.add_argument("--output", type=Path, required=True)
    restoring.add_argument("--figures", action="store_true")
    rebuilding = commands.add_parser("refresh", help="Trusted private main-branch CI entry point")
    rebuilding.add_argument("--checkout", type=Path, default=Path.cwd())
    commands.add_parser("schema", help="Print closed configuration and transport schemas")
    checking = commands.add_parser("check-storage", help="Verify local private working volumes; does not enable disk encryption")
    checking.add_argument("--path", type=Path, action="append", required=True)
    verification = commands.add_parser("verify", help="Verify encrypted sources and figures against independently pinned signing identity")
    verification.add_argument("--checkout", type=Path, default=Path.cwd())
    verification.add_argument("--signing-fingerprint", required=True, help="Trusted fingerprint retained separately from the artifact")
    verification.add_argument("--figures", action="store_true")
    inventory = commands.add_parser(
        "inventory", help="List current managed ciphertext digests; retained history and external storage are separate"
    )
    inventory.add_argument("--checkout", type=Path, default=Path.cwd())
    candidate = commands.add_parser("rotation-keys", help="Explicitly create/reuse a separate key backup and a private candidate JSON file")
    candidate.add_argument("--repo", required=True)
    candidate.add_argument("--key-dir", type=Path, required=True)
    candidate.add_argument("--rotate-by", required=True, help="Next rotation deadline, YYYY-MM-DD in UTC")
    candidate.add_argument("--output", type=Path, required=True)
    rotating = commands.add_parser("rotate", help="Prepare verified previous/current snapshots without modifying the live checkout")
    rotating.add_argument("--checkout", type=Path, required=True)
    rotating.add_argument("--key-dir", type=Path, required=True)
    rotating.add_argument("--candidate", type=Path, required=True, help="Private JSON file, never credentials on the command line")
    rotating.add_argument("--output", type=Path, required=True)
    promoting = commands.add_parser("promote-keys", help="Explicitly update existing primary Actions secrets after published rotation")
    promoting.add_argument("--checkout", type=Path, required=True)
    promoting.add_argument("--key-dir", type=Path, required=True)
    for command in ("prepare-refresh", "publish-refresh"):
        prepared = commands.add_parser(command, help="Trusted private main pipeline stage; publication requires verified preparation")
        prepared.add_argument("--checkout", type=Path, default=Path.cwd())
        prepared.add_argument("--output", type=Path, required=True)
    for command in ("seal-file", "restore-file"):
        managed = commands.add_parser(command, help="Explicitly manage one opaque file outside the source archive allowlist")
        managed.add_argument("--checkout", type=Path, required=True)
        managed.add_argument("--key-dir", type=Path, required=True)
        managed.add_argument("--name", required=True, help="Non-sensitive opaque identifier")
        managed.add_argument("--source" if command == "seal-file" else "--output", type=Path, required=True)
    export_cli.register(commands)
    args = parser.parse_args(argv)
    os.umask(0o077)
    today = datetime.now(UTC).date()

    try:
        if args.command in {"export", "verify-export", "restore-export"}:
            export_cli.dispatch(args, today)
        elif args.command == "schema":
            print(json.dumps({"config": schema(Config), "envelope": schema(Envelope), "export": schema(Manifest)}, indent=2))
        elif args.command == "check-storage":
            for path in args.path:
                require_protected(path)
            print("Requested local working volumes passed encryption checks; remote databases were not inspected.")
        elif args.command == "verify":
            config = load_config(args.checkout)
            if config.signing_fingerprint != args.signing_fingerprint:
                raise ValueError("The independently trusted signing fingerprint differs")
            # The publication tree must contain ciphertext rather than a second cleartext copy of source records.
            tracked = run(["git", "ls-files", "-z"], cwd=args.checkout).decode().split("\0")
            if any(
                archive.allowed(name) or (name.startswith("knowledge/") and name.endswith(".jsonl")) or ".sqlite" in name
                for name in tracked
                if name
            ):
                raise ValueError("Plaintext source records or indexes remain tracked in the encrypted collection checkout")
            artifact = args.checkout / (FIGURES if args.figures else SOURCE)
            verify(artifact, args.checkout / "collection/cosign.pub", config)
            expected = Path(str(artifact) + ".sha256").read_text().strip()
            if hashlib.sha256(artifact.read_bytes()).hexdigest() != expected:
                raise ValueError("Ciphertext checksum differs from the verified artifact")
            print("Encrypted artifact signature verified against the independently trusted signing fingerprint.")
        elif args.command == "inventory":
            print(json.dumps({name: hashlib.sha256(data).hexdigest() for name, data in snapshot(args.checkout).items()}, indent=2))
        elif args.command == "rotation-keys":
            export_candidate(args.key_dir, args.repo, args.rotate_by, args.output, today)
            print("Private candidate saved; review before uploading WITFUL_COLLECTION_NEXT_KEYS. Old keys remain required for history.")
        elif args.command == "rotate":
            require_protected(args.candidate)
            require_protected(args.output)
            if (
                args.candidate.is_symlink()
                or not args.candidate.is_file()
                or args.candidate.stat().st_mode & 0o077
                or args.candidate.stat().st_size > 32768
            ):
                raise ValueError("Candidate credentials must be a private regular file")
            config = load_config(args.checkout)
            pending = read_candidate(args.candidate.read_text(), config.repository, today)
            rotate(args.checkout, read_keys(args.key_dir), pending, args.output, today)
            print("Verified previous/current snapshots prepared. Review and publish the complete generation in one signed commit.")
        elif args.command == "promote-keys":
            config = load_config(args.checkout)
            private_repository(config.repository)
            verify_snapshot(args.checkout, read_keys(args.key_dir))
            published = run(
                ["gh", "api", "--hostname", "github.com", f"repos/{config.repository}/contents/{CONFIG}?ref=main", "--jq", ".content"]
            )
            if base64.b64decode(published).strip() != (args.checkout / CONFIG).read_bytes().strip():
                raise ValueError("Publish and verify the new configuration on main before promoting its secrets")
            project_keys(args.key_dir, config.repository)
            print("Primary secrets projected from the verified key backup. Retain old backups; review before clearing NEXT_KEYS.")
        elif args.command == "prepare-refresh":
            prepare_refresh(args.checkout, args.output, dict(os.environ), today)
            print("Complete private publication candidate verified; no active files or remote secrets changed.")
        elif args.command == "publish-refresh":
            print(publish(args.checkout, args.output, dict(os.environ)))
        elif args.command == "seal-file":
            seal_file(args.checkout, args.source, args.key_dir, args.name, today)
            print("Managed file sealed; review the complete encrypted file set and configuration before publication.")
        elif args.command == "restore-file":
            restore_file(args.checkout, args.key_dir, args.name, args.output)
            print("Managed file restored to the new protected destination.")
        elif args.command == "setup":
            directory = (
                args.key_dir
                or Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
                / "witful/collections"
                / hashlib.sha256(args.repo.lower().encode()).hexdigest()[:24]
            )
            setup(args.repo, args.checkout, args.home, directory, create=args.create, restore_existing=args.restore)
        elif args.command == "seal":
            seal(args.checkout, args.source, args.key_dir)
            print("Encrypted source and signature updated; commit and push the named collection files.")
        elif args.command == "restore":
            restore(args.checkout, args.key_dir, args.output, "figures" if args.figures else "sources")
            print("Verified collection restored into the selected new directory.")
        else:
            refresh(args.checkout)
            print("Current collection figures regenerated and encrypted; no source values were logged.")
    except StorageProtectionError as error:
        parser.exit(2, f"{error}\n")
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, InvalidTag, UnsupportedAlgorithm, ValidationError):
        parser.exit(
            2,
            "Collection operation failed. Check private repository access, key backups, trust pins, "
            "and source validation locally; private diagnostics were withheld.\n",
        )

    return 0
