"""
Bind the CI contract-test result to its source, locked SDKs and vendor snapshots.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import tomllib
from importlib.metadata import version
from pathlib import Path


def main() -> int:
    """
    Write non-sensitive input provenance alongside the separately produced JUnit result.

    Returns:
        int: Zero after writing; mismatched installed SDK versions fail before tests.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Immutable source revision checked out by this run")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source):
        parser.error("--source must be a full Git revision")
    root = Path(__file__).resolve().parents[3]
    lock = (root / "poetry.lock").read_bytes()
    packages = tomllib.loads(lock.decode())["package"]
    installed = {name: version(name) for name in ("PyGithub", "python-gitlab", "openapi-schema-validator")}
    for name, selected in installed.items():
        expected = next(item["version"] for item in packages if item["name"].lower() == name.lower())
        if selected != expected:
            raise ValueError(f"{name}: installed version differs from the committed lock")
    manifest = Path(__file__).with_name("data") / "manifest.json"
    result = {
        "source_revision": args.source,
        "python": platform.python_version(),
        "installed_packages": installed,
        "poetry_lock_sha256": hashlib.sha256(lock).hexdigest(),
        "vendor_contracts": json.loads(manifest.read_text()),
        "test_result": "See junit.xml from this run; this document records inputs, not success.",
        "scope": "Local HTTP mocks and response schemas, not live SaaS behavior or a running vendor platform.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(manifest.parent, args.output.parent / "contracts", dirs_exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
