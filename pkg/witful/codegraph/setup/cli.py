"""
Own explicit optional CodeGraph custody setup without weakening native admission or starting services implicitly.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
from typing import TYPE_CHECKING

from witful.codegraph.setup.custody import provision
from witful.codegraph.setup.onepassword import OnePassword
from witful.collection.protection import require_protected
from witful.exceptions import SetupError, StorageProtectionError

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


def prepare(directory: Path) -> Path:
    """
    Require an owner-only setup directory on protected storage outside every Git worktree.

    Args:
        directory (Path): Operator-selected local setup directory.

    Returns:
        Path: Canonical validated directory.

    Raises:
        SetupError: A symlink, repository, ownership or permission boundary is unsafe.
    """
    selected = directory.expanduser().absolute()
    if any(path.is_symlink() for path in (selected, *selected.parents)):
        raise SetupError("Choose a setup directory without symlink components.")
    ancestor = selected
    while not ancestor.exists():
        ancestor = ancestor.parent
    require_protected(ancestor)
    result = subprocess.run(["git", "-C", str(ancestor), "rev-parse", "--git-dir"], capture_output=True, check=False)
    if result.returncode == 0:
        raise SetupError("Place setup files outside Git repositories.")
    selected.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = selected.stat()
    if not selected.is_dir() or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise SetupError("Setup directory must be owned by the current user with mode 0700.")
    return selected


def execute(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """
    Provision the explicit operator setup with a process-scoped lock and redacted failure messages.

    Args:
        args (argparse.Namespace): Shared-builder setup leaf arguments.
        parser (argparse.ArgumentParser): Owning leaf parser.

    Returns:
        int: Zero for verified saved custody references, one for an actionable setup failure.
    """
    del parser
    try:
        directory = prepare(args.directory)
        descriptor = os.open(directory / ".setup.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SetupError("Another setup owns this directory; wait for it to finish.") from None
            provision(
                OnePassword.installed(args.account),
                directory,
                args.vault,
                args.provision,
                args.wrapping_reference,
                args.signing_reference,
                args.token_reference,
            )
        print("Verified custody references saved. Private key and token values remain in 1Password.")
        print("Native runtime admission and repository enrollment remain separate; see docs/codegraph-setup.md.")
        return 0
    except SetupError as error:
        print(str(error), file=sys.stderr)
    except (OSError, StorageProtectionError):
        print("Setup blocked: verify protected storage, private permissions and installed prerequisites. Values withheld.", file=sys.stderr)
    except KeyboardInterrupt:
        print("Setup cancelled. Preserve receipts and reconcile any pending account before retrying.", file=sys.stderr)
        return 130
    return 1
