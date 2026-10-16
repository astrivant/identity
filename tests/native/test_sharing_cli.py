"""
Exercise real offline recipient decryption and configured sharing boundaries without live custody or implicit trust.
"""

from __future__ import annotations

import base64
import json
from http import HTTPStatus
from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
from attrs import evolve
from cryptography.hazmat.primitives import serialization
from witful import cli
from witful.collection import exports
from witful.knowledge.contracts import as_data, schema
from witful.native import cli as native_cli
from witful.native import codec, sharing_cli
from witful.native.api.admission import Admission
from witful.native.api.builder import Builder
from witful.native.config import ExportRecipient, Trust
from witful.native.sharing import PrivateRecipient, create
from witful.native.sharing_cli import Expectation
from witful.native.wire import mapping

from tests.native.recipients import receiver
from tests.native.requests import body
from tests.native.runtime import lesson

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from tests.native.conftest import Fixture
    from tests.native.database import Databases
    from tests.native.runtime import Runtime


def test_scoped_recipient_api(runtime: Runtime, fixture: Fixture) -> None:
    """
    Refuse aliases for another identity and arbitrary recipient data while retaining configured owner and recipient exports.

    Args:
        runtime (Runtime): Actual admitted storage backend.
        fixture (Fixture): Synthetic sender custody.

    Returns:
        None: Shared responses preserve sender signing, no-store headers and scoped encryption selection.
    """
    recipient, reader = receiver(fixture)
    configured = ExportRecipient(
        "reviewer",
        runtime.access.scope.tenant,
        runtime.access.scope.identity,
        recipient.generation,
        base64.b64encode(recipient.public).decode(),
        recipient.fingerprint,
    )
    client = (
        Builder(
            runtime.service,
            Admission(1),
            lambda: True,
            lambda: runtime.access.subject,
            recipients=(configured, evolve(configured, name="other", identity=str(uuid4()))),
        )
        .build()
        .test_client()
    )
    for arguments in ({"recipient": "other"}, {"recipient": "missing"}, {"recipient": {"public": "not-reviewed"}}):
        response = client.post("/v1/share", data=body(runtime, arguments), content_type="application/cbor")
        assert response.status_code in {HTTPStatus.FORBIDDEN, HTTPStatus.BAD_REQUEST}
    response = client.post("/v1/share", data=body(runtime, {"recipient": "reviewer"}), content_type="application/cbor")
    assert response.status_code == HTTPStatus.OK and response.headers["Cache-Control"] == "no-store"
    package = mapping(codec.decode(response.data), {"context", "sealed"})
    assert isinstance(package["sealed"], bytes)
    assert recipient.public not in package["sealed"]
    assert reader.signing == fixture.service.signing
    response = client.post("/v1/share", data=body(runtime, {"recipient": None}), content_type="application/cbor")
    assert response.status_code == HTTPStatus.OK


def test_export_rechecks_revoked_grant(runtime: Runtime, databases: Databases) -> None:
    """
    Revoke export authority after decryption but before release and ensure no package reaches the caller.

    Args:
        runtime (Runtime): Current admitted source.
        databases (Databases): Independently administered synthetic authority connection.

    Returns:
        None: Current result-release authority remains mandatory for a previously admitted export.
    """
    calls = 0

    def revoke() -> float:
        """
        Remove the grant on the signed payload's time observation, after initial admission.

        Returns:
            float: Stable synthetic time within the original grant interval.
        """
        nonlocal calls
        calls += 1
        if calls == 2:
            with psycopg.connect(databases.authority_admin) as admin:
                admin.execute("DELETE FROM witful_native_grants WHERE id=%s", (runtime.access.grant,))
        return 100.0

    client = (
        Builder(evolve(runtime.service, clock=revoke), Admission(1), lambda: True, lambda: runtime.access.subject).build().test_client()
    )
    response = client.post("/v1/share", data=body(runtime, {"recipient": None}), content_type="application/cbor")
    assert calls >= 2 and response.status_code == HTTPStatus.FORBIDDEN
    assert response.data == codec.encode({"code": "denied"})


def test_offline_cli_independent_keys_and_frontier(
    runtime: Runtime, fixture: Fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Read real encrypted exports with only recipient custody and reject rollback, changed pins and unsafe file permissions.

    Args:
        runtime (Runtime): Synthetic native history.
        fixture (Fixture): Sender keys removed before offline execution.
        tmp_path (Path): Synthetic-only file workspace.
        monkeypatch (pytest.MonkeyPatch): Explicit test substitute for host volume attestation, never for cryptographic checks.
        capsys (pytest.CaptureFixture[str]): Redacted CLI output capture.

    Returns:
        None: Offline verification matches the independently selected frontier and never prints private records.
    """
    for module in (sharing_cli, exports, native_cli):
        monkeypatch.setattr(module, "require_protected", lambda _: None)
    entry = lesson("synthetic-offline-canary")
    runtime.service.append(runtime.access, str(uuid4()), "main", None, (entry,), b"exact original source")
    recipient, reader = receiver(fixture)
    context, sealed = create(runtime.service, runtime.access, recipient)
    head = runtime.service.store.head(runtime.access.scope)
    trust = Expectation(
        context,
        head.generation,
        head.root,
        head.digest.hex(),
        recipient.generation,
        reader.signing,
        tuple(
            Trust(generation, base64.b64encode(signer.public).decode(), signer.fingerprint) for generation, signer in reader.signers.items()
        ),
    )
    assert schema(Expectation)["type"] == "object"
    trust_path, private_path, password_path = (tmp_path / name for name in ("trust.json", "key.pem", "password"))
    trust_path.write_text(json.dumps(as_data(trust)))
    assert isinstance(reader.keys, PrivateRecipient)
    private_path.write_bytes(
        reader.keys.key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(b"synthetic-password")
        )
    )
    password_path.write_bytes(b"synthetic-password")
    for path in (trust_path, private_path, password_path):
        path.chmod(0o600)
    package, output = tmp_path / "shared.cbor", tmp_path / "review.json"
    package.write_bytes(codec.encode({"context": context.data(), "sealed": sealed}))
    fixture.keys.wrapping.clear()
    fixture.keys.signing.clear()
    args = [
        "native",
        "recovery",
        "inspect",
        "--input",
        str(package),
        "--trust",
        str(trust_path),
        "--private-key",
        str(private_path),
        "--password-file",
        str(password_path),
        "--output",
        str(output),
    ]
    assert cli.main(args) == 0
    value = json.loads(output.read_text())
    assert isinstance(value, dict) and isinstance(value["revisions"], list)
    assert base64.b64decode(value["revisions"][0]["source_base64"]) == b"exact original source"
    assert output.stat().st_mode & 0o077 == 0
    assert "canary" not in str(capsys.readouterr())
    output.unlink()
    trust_path.write_text(json.dumps(as_data(evolve(trust, generation=0))))
    assert cli.main(args) == 1 and not output.exists()
    trust_path.write_text(json.dumps(as_data(evolve(trust, signers=(evolve(trust.signers[0], fingerprint="0" * 64),)))))
    assert cli.main(args) == 1 and not output.exists()
    trust_path.write_text(json.dumps(as_data(trust)))
    private_path.chmod(0o644)
    assert cli.main(args) == 1 and not output.exists()
    assert "canary" not in str(capsys.readouterr())
