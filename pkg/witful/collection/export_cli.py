"""
Resolve installed collection defaults and expose offline identity export operations.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from witful.collection.exports import create, read_file, restore_export, verify_export
from witful.collection.material import read_keys
from witful.collection.models import load_config
from witful.collection.rotation import select_keys

if TYPE_CHECKING:
    import argparse
    from datetime import date

    from witful.collection.material import Material


def defaults(home: Path, checkout: Path | None, directory: Path | None, env: dict[str, str], today: date) -> tuple[Path, Material]:
    """
    Select explicit owner keys, matching installed defaults, or the existing active environment generation.

    Args:
        home (Path): Home containing collection/.setup.json from the installer.
        checkout (Path | None): Explicit collection; otherwise receipt checkout or current working directory.
        directory (Path | None): Explicit existing owner key backup, preferred over installed defaults.
        env (dict[str, str]): Existing collection and Cosign environment names, used only without a local backup.
        today (date): Explicit UTC key policy clock.

    Returns:
        tuple[Path, Material]: Selected collection and its independently checked active generation.

    Raises:
        ValueError: The receipt is malformed, references another repository, or keys do not match the active generation.
    """
    receipt = home / "collection/.setup.json"
    metadata: dict[str, str] = {}
    if receipt.exists() and (checkout is None or directory is None):
        data: object = json.loads(read_file(receipt, private=True))
        if not isinstance(data, dict) or set(data) != {"repository", "checkout", "keys", "command"}:
            raise ValueError("Invalid installed collection receipt")
        for key, value in data.items():
            if not isinstance(key, str) or not isinstance(value, str) or not value:
                raise ValueError("Invalid installed collection receipt value")
            metadata[key] = value
    root = checkout or (Path(metadata["checkout"]) if metadata else Path.cwd())
    config = load_config(root)
    installed = metadata and Path(metadata["checkout"]).resolve() == root.resolve()
    if installed and metadata["repository"] != config.repository:
        raise ValueError("Installed collection repository differs from its configuration")
    selected = directory or (Path(metadata["keys"]) if installed else None)
    keys = read_keys(selected) if selected is not None else select_keys(root, env, today)[0]
    return root, keys


def dispatch(args: argparse.Namespace, today: date) -> None:
    """
    Execute one registered operation using path inputs instead of private command-line values.

    Args:
        args (argparse.Namespace): Arguments from the collection parser.
        today (date): UTC date captured by the parent command.

    Returns:
        None: The export is created, verified or restored; diagnostics contain no private records.
    """
    if args.command == "export":
        checkout, keys = defaults(args.home, args.checkout, args.key_dir, dict(os.environ), today)
        recipient = read_file(args.recipient_key) if args.recipient_key is not None else None
        create(checkout, keys, args.output, today, recipient)
        print("Signed encrypted export created from sealed records. Review its scope before sharing; no private keys are included.")
    elif args.command == "verify-export":
        verify_export(args.bundle, args.signing_fingerprint)
        print("Complete export verified against the independently trusted sender fingerprint.")
    else:
        restore_export(
            args.bundle,
            args.signing_fingerprint,
            read_file(args.private_key, private=True),
            read_file(args.password_file, private=True),
            args.output,
        )
        print("Verified identity records restored to the new protected destination; no identity was activated or merged.")
