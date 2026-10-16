"""
Verify hosted release bytes and registry files before announcing publication.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_public_key
from witful.knowledge.contracts import structure

from .feedback import Inventory, resolve_commit, version

if TYPE_CHECKING:
    from pathlib import Path

    from github.GitRelease import GitRelease
    from github.Repository import Repository


def digest(path: Path) -> str:
    """
    Hash one bounded downloaded or locally built artifact.

    Args:
        path (Path): Artifact path.

    Returns:
        str: SHA-256 content digest.
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def registry_files(tag: str, artifacts: tuple[Path, ...]) -> bool:
    """
    Compare downloaded PyPI distributions with the exact accepted build artifacts.

    Args:
        tag (str): Verified stable release version.
        artifacts (tuple[Path, ...]): Accepted wheels and source distributions.

    Returns:
        bool: True when all files match; false while registry file metadata is still incomplete.

    Raises:
        ValueError: The registry differs from the accepted source build.
    """
    with urlopen(f"https://pypi.org/pypi/witful/{tag[1:]}/json", timeout=30) as response:
        payload: object = json.load(response)
    if not isinstance(payload, dict) or not isinstance(payload.get("urls"), list):
        raise ValueError("Invalid registry metadata")
    rows = payload["urls"]
    for artifact in artifacts:
        row = next((item for item in rows if isinstance(item, dict) and item.get("filename") == artifact.name), None)
        if row is None:
            return False
        if row.get("yanked") is not False or not isinstance(row.get("digests"), dict) or row["digests"].get("sha256") != digest(artifact):
            raise ValueError("Registry artifact differs from accepted build")
        url = row.get("url")
        if not isinstance(url, str) or urlsplit(url).scheme != "https" or urlsplit(url).hostname != "files.pythonhosted.org":
            raise ValueError("Invalid registry artifact destination")
        with urlopen(url, timeout=30) as response:
            content = response.read(artifact.stat().st_size + 1)
        if hashlib.sha256(content).hexdigest() != digest(artifact):
            raise ValueError("Downloaded registry artifact differs from accepted build")

    return True


def verify_registry(tag: str, artifacts: tuple[Path, ...]) -> None:
    """
    Retry bounded registry propagation failures without retrying integrity mismatches.

    Args:
        tag (str): Verified stable release version.
        artifacts (tuple[Path, ...]): Accepted build files.

    Returns:
        None: Registry verification succeeded within the retry budget.
    """
    for attempt in range(4):
        try:
            if registry_files(tag, artifacts):
                return
            if attempt == 3:
                raise ValueError("Registry files remain incomplete")
        except HTTPError as error:
            if error.code not in {HTTPStatus.NOT_FOUND, HTTPStatus.TOO_MANY_REQUESTS} and error.code < HTTPStatus.INTERNAL_SERVER_ERROR:
                raise
            if attempt == 3:
                raise
        except (URLError, TimeoutError):
            if attempt == 3:
                raise
        time.sleep(2**attempt)


def verify_release(
    repository: Repository, tag: str, source: str, built: Path, destination: Path, fingerprint: str
) -> tuple[GitRelease, Inventory]:
    """
    Verify the complete published attachment set, trusted signing identity and PyPI bytes.

    Args:
        repository (Repository): SDK repository bound to this workflow.
        tag (str): Exact version to verify.
        source (str): Immutable source commit from this run.
        built (Path): Distribution artifacts downloaded from this run's build job.
        destination (Path): Empty private directory for published artifact verification.
        fingerprint (str): Public-key digest derived in the trusted signing job.

    Returns:
        tuple[GitRelease, Inventory]: Published release and its authenticated contribution inventory.

    Raises:
        ValueError: Publication, provenance, signing or content verification failed.
    """
    version(tag)
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("Missing trusted signing fingerprint")
    release = repository.get_release(tag)
    if release.draft or release.prerelease or resolve_commit(repository, tag) != source:
        raise ValueError("Release is not published from the expected stable source")
    artifacts = tuple(sorted((*built.glob("*.whl"), *built.glob("*.tar.gz"))))
    if not any(path.suffix == ".whl" for path in artifacts) or not any(path.name.endswith(".tar.gz") for path in artifacts):
        raise ValueError("Accepted build artifacts are incomplete")
    expected = {path.name for path in artifacts} | {path.name + ".sigstore.json" for path in artifacts}
    expected |= {"SOURCE.json", "RELEASE.json", "cosign.pub", "public-key.sha256", "SHA256SUMS", "SHA256SUMS.sigstore.json"}
    assets = list(release.get_assets())
    if len(assets) != len(expected) or {asset.name for asset in assets} != expected:
        raise ValueError("Published attachment set is incomplete or unexpected")
    destination.mkdir(parents=True, exist_ok=False)
    for asset in assets:
        if not 0 < asset.size <= 512 * 1024 * 1024:
            raise ValueError("Published asset exceeds the verification budget")
        asset.download_asset(str(destination / asset.name), chunk_size=65536)
        if (destination / asset.name).stat().st_size != asset.size:
            raise ValueError("Incomplete asset download")

    # The job output is the trust anchor; the key bundled with an untrusted download is not.
    public = load_pem_public_key((destination / "cosign.pub").read_bytes())
    actual = hashlib.sha256(public.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)).hexdigest()
    if actual != fingerprint or not (destination / "public-key.sha256").read_text().strip().endswith(fingerprint):
        raise ValueError("Published signing identity differs from the trusted job")
    signed = ["SHA256SUMS", *[path.name for path in artifacts]]
    for name in signed:
        result = subprocess.run(
            [
                "cosign",
                "verify-blob",
                "--key",
                str(destination / "cosign.pub"),
                "--bundle",
                str(destination / (name + ".sigstore.json")),
                str(destination / name),
            ],
            capture_output=True,
            check=False,
            timeout=90,
        )
        if result.returncode:
            raise ValueError("Published signature verification failed")
    checksums: dict[str, str] = {}
    for line in (destination / "SHA256SUMS").read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  \./([^/]+)", line)
        if not match or match[2] in checksums:
            raise ValueError("Invalid published checksum manifest")
        checksums[match[2]] = match[1]
    if set(checksums) != expected - {"SHA256SUMS", "SHA256SUMS.sigstore.json"}:
        raise ValueError("Checksum manifest coverage differs from the release")
    if any(digest(destination / name) != checksum for name, checksum in checksums.items()):
        raise ValueError("Published bytes differ from the signed manifest")
    if any(digest(destination / path.name) != digest(path) for path in (*artifacts, built / "SOURCE.json")):
        raise ValueError("Published files differ from this run's build")
    if json.loads((destination / "SOURCE.json").read_text()) != {"commit": source, "tag": tag}:
        raise ValueError("Published build provenance differs from this run")
    value = structure(json.loads((destination / "RELEASE.json").read_text()), Inventory)
    if (value.repository, value.tag, value.source) != (repository.full_name, tag, source):
        raise ValueError("Release inventory is bound to another source")
    verify_registry(tag, artifacts)
    return release, value
