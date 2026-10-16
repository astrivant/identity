"""
Reject incomplete, changed or unverified artifacts before contributor notification.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from email.message import Message
from http import HTTPStatus
from io import BytesIO
from typing import TYPE_CHECKING
from urllib.error import HTTPError

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from release import verification
from release.feedback import Inventory
from witful.knowledge.contracts import as_data

from tests.releases.conftest import PREFIX, SOURCE
from tests.support.provider_contracts import response_body

if TYPE_CHECKING:
    from pathlib import Path

    from tests.releases.conftest import Host


def publication(host: Host, root: Path) -> tuple[Path, str, dict[str, bytes]]:
    """
    Build complete synthetic public assets while keeping accepted build files separate.

    Args:
        host (Host): Loopback GitHub SDK service.
        root (Path): Disposable verification root.

    Returns:
        tuple[Path, str, dict[str, bytes]]: Accepted build, trusted fingerprint and published payloads.
    """
    built = root / "built"
    built.mkdir()
    public = Ed25519PrivateKey.generate().public_key()
    fingerprint = hashlib.sha256(public.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)).hexdigest()
    payloads = {
        "witful-1.1.0-py3-none-any.whl": b"synthetic wheel bytes",
        "witful-1.1.0.tar.gz": b"synthetic source bytes",
        "SOURCE.json": json.dumps({"commit": SOURCE, "tag": "v1.1.0"}).encode(),
    }
    for name, content in payloads.items():
        (built / name).write_bytes(content)
    payloads.update({name + ".sigstore.json": b"synthetic signature bundle" for name in payloads if name != "SOURCE.json"})
    payloads.update(
        {
            "cosign.pub": public.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo),
            "public-key.sha256": f"SHA2-256(stdin)= {fingerprint}\n".encode(),
            "RELEASE.json": json.dumps(as_data(Inventory("example/project", "v1.1.0", SOURCE, "", "", ()))).encode(),
        }
    )
    payloads["SHA256SUMS"] = "".join(f"{hashlib.sha256(content).hexdigest()}  ./{name}\n" for name, content in payloads.items()).encode()
    payloads["SHA256SUMS.sigstore.json"] = b"synthetic manifest signature"
    url = host.repository.url
    host.responses[PREFIX + "/releases/tags/v1.1.0"] = response_body(
        "github",
        "release",
        {
            "id": 7,
            "url": url + "/releases/7",
            "tag_name": "v1.1.0",
            "draft": False,
            "prerelease": False,
            "assets_url": url + "/releases/7/assets",
            "html_url": "https://github.com/example/project/releases/tag/v1.1.0",
        },
    )
    assets = []
    for identifier, (name, content) in enumerate(payloads.items(), 1):
        path = PREFIX + f"/releases/assets/{identifier}"
        assets.append({"id": identifier, "name": name, "size": len(content), "url": url + f"/releases/assets/{identifier}"})
        host.responses[path] = content
    host.responses[PREFIX + "/releases/7/assets"] = response_body("github", "release_assets", assets)
    return built, fingerprint, payloads


@pytest.mark.parametrize("defect", ["none", "key", "bytes", "missing", "signature", "source", "draft"])
def test_published_verification_rejects_each_independent_boundary(
    host: Host, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    """
    Verify downloaded SDK assets before registry checks or contributor comments.

    Args:
        host (Host): Schema-validated GitHub test server.
        tmp_path (Path): Isolated accepted and downloaded artifacts.
        monkeypatch (pytest.MonkeyPatch): Explicit signature-runner and registry test boundaries.
        defect (str): Publication boundary to invalidate.

    Returns:
        None: Only the complete verified scenario can reach the registry check.
    """
    built, fingerprint, payloads = publication(host, tmp_path)
    registry_calls: list[str] = []
    signatures: list[list[str]] = []

    def cosign(arguments: list[str], **options: object) -> subprocess.CompletedProcess[bytes]:
        """
        Model the verifier process result without presenting synthetic bundles as real signatures.

        Args:
            arguments (list[str]): Actual Cosign command.
            **options (object): Captured process settings.

        Returns:
            subprocess.CompletedProcess[bytes]: Deliberate verification outcome.
        """
        assert arguments[:2] == ["cosign", "verify-blob"]
        assert options["timeout"] == 90
        signatures.append(arguments)
        return subprocess.CompletedProcess(arguments, 1 if defect == "signature" else 0, b"", b"")

    def registry(tag: str, artifacts: tuple[Path, ...]) -> None:
        """
        Observe the registry gate without reaching a public service.

        Args:
            tag (str): Expected release version.
            artifacts (tuple[Path, ...]): Expected accepted distributions.

        Returns:
            None: A local invocation receipt is retained.
        """
        assert len(artifacts) == 2
        registry_calls.append(tag)

    monkeypatch.setattr("release.verification.subprocess.run", cosign)
    monkeypatch.setattr(verification, "verify_registry", registry)
    if defect == "key":
        fingerprint = "0" * 64
    elif defect == "bytes":
        host.responses[PREFIX + "/releases/assets/1"] = b"altered".ljust(len(next(iter(payloads.values()))), b" ")
    elif defect == "missing":
        rows = host.responses[PREFIX + "/releases/7/assets"]
        assert isinstance(rows, list)
        host.responses[PREFIX + "/releases/7/assets"] = rows[:-1]
    elif defect == "source":
        (built / "SOURCE.json").write_text("{}")
    elif defect == "draft":
        row = host.responses[PREFIX + "/releases/tags/v1.1.0"]
        assert isinstance(row, dict)
        row["draft"] = True
    if defect == "none":
        release, value = verification.verify_release(host.repository, "v1.1.0", SOURCE, built, tmp_path / "download", fingerprint)
        assert not release.draft and value.source == SOURCE
        assert registry_calls == ["v1.1.0"] and len(signatures) == 3
    else:
        with pytest.raises(ValueError):
            verification.verify_release(host.repository, "v1.1.0", SOURCE, built, tmp_path / "download", fingerprint)
        assert not registry_calls
    assert not host.posts


def test_registry_checks_real_file_bytes_and_retries_only_propagation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Allow delayed registry metadata while rejecting yanked, changed and corrupted artifacts.

    Args:
        tmp_path (Path): Accepted file directory.
        monkeypatch (pytest.MonkeyPatch): Isolated HTTP and retry-clock boundaries.

    Returns:
        None: Propagation recovers, but an integrity mismatch is not retried or accepted.
    """
    artifact = tmp_path / "witful-1.1.0.tar.gz"
    artifact.write_bytes(b"accepted bytes")
    row: dict[str, object] = {
        "filename": artifact.name,
        "yanked": False,
        "digests": {"sha256": verification.digest(artifact)},
        "url": "https://files.pythonhosted.org/synthetic-package",
    }
    attempts: list[str] = []
    delays: list[int] = []

    def response(url: str, timeout: int) -> BytesIO:
        """
        Return propagation failures followed by matching metadata and download bytes.

        Args:
            url (str): Explicit registry endpoint.
            timeout (int): Required network timeout.

        Returns:
            BytesIO: Synthetic public response body.
        """
        attempts.append(url)
        assert timeout == 30
        if len(attempts) == 1:
            raise HTTPError(url, HTTPStatus.NOT_FOUND, "Not yet visible", Message(), None)
        return BytesIO(json.dumps({"urls": [row]}).encode() if url.endswith("/json") else artifact.read_bytes())

    monkeypatch.setattr(verification, "urlopen", response)
    monkeypatch.setattr("release.verification.time.sleep", delays.append)
    verification.verify_registry("v1.1.0", (artifact,))
    assert len(attempts) == 3 and delays == [1]
    attempts.clear()
    row["yanked"] = True
    with pytest.raises(ValueError, match="differs"):
        verification.verify_registry("v1.1.0", (artifact,))
    assert len(attempts) == 2
