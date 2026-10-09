"""
Bootstrap the current checkout on macOS/Linux, then delegate to the packaged collection installer.
"""

from __future__ import annotations

import subprocess
import sys
import venv
from pathlib import Path


def main() -> int:
    """
    Install the current library without modifying the global Python or existing Codex configuration.

    Returns:
        int: Installer status; two for an unsupported interpreter or dependency installation failure.
    """
    if "--help" in sys.argv or "-h" in sys.argv:
        print(
            "Usage: python3 scripts/collection/install.py --repo OWNER/REPO [--create] [--restore] "
            "[--checkout PATH] [--home PATH] [--key-dir PATH]\n"
            "Requires Python 3.12+ (except 3.14.1), Git, gh, ssh-keygen, OpenSSL, and Cosign 3.x.\n"
            "Creates or reuses dedicated key backups and projects repository secrets. See docs/private-collections.md."
        )
        return 0

    if sys.version_info < (3, 12) or sys.version_info[:3] == (3, 14, 1):
        print("Use Python 3.12+ excluding 3.14.1.", file=sys.stderr)
        return 2

    root = Path(__file__).resolve().parents[2]
    environment = root / ".cache/collection-installer"
    python = environment / "bin/python"

    try:
        if not python.exists():
            venv.EnvBuilder(with_pip=True).create(environment)
        subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", str(root)], check=True, timeout=300)
        return subprocess.run([str(environment / "bin/witful"), "collection", "setup", *sys.argv[1:]], check=False).returncode
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print("Installer dependency setup failed; inspect package installation and retry.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
