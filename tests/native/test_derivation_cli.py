"""
Drive a protected review document through the recursive CLI and real application into independently scoped native storage.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING
from uuid import uuid4

from witful import cli
from witful.knowledge.contracts import as_data
from witful.native import cli as native_cli
from witful.native import codec
from witful.native.api.admission import Admission
from witful.native.api.builder import Builder
from witful.native.client import Client, ClientSettings
from witful.native.config import DerivationTarget

from tests.native.derivation import children
from tests.native.requests import body

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from tests.native.database import Databases
    from tests.native.runtime import Runtime


def test_cli_review_reaches_atomic_publication(
    runtime: Runtime,
    databases: Databases,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Parse one review once, preserve typed domain data and invoke the actual API/storage contract behind an explicit test transport seam.

    Args:
        runtime (Runtime): Real native parent.
        databases (Databases): Independent synthetic authority provisioning.
        tmp_path (Path): Synthetic protected-file substitute.
        monkeypatch (pytest.MonkeyPatch): Replace only host volume attestation and HTTP transport, not API policy or persistence.

    Returns:
        None: The CLI's split command produces both independently readable children and a durable parent receipt.
    """
    expected, outputs = children(runtime, databases)
    aliases = tuple(
        DerivationTarget(
            f"recipient-{index}",
            child.service.authority.backend,
            child.access.scope.tenant,
            child.access.scope.identity,
            child.access.grant,
            child.access.task,
            child.access.epoch,
            child.access.policy,
        )
        for index, child in enumerate(outputs)
    )
    app = Builder(runtime.service, Admission(1), lambda: True, lambda: runtime.access.subject, derivations=aliases).build().test_client()

    def invoke(client: Client, operation: str, arguments: object) -> object:
        """
        Bridge the CLI's real binary arguments into the actual consolidated app without pretending to test TLS here.

        Args:
            client (Client): Parsed native client configuration.
            operation (str): Selected internal operation.
            arguments (object): Actual typed CLI request.

        Returns:
            object: Decoded real application response.
        """
        assert client.settings.identity == runtime.access.scope.identity and operation == "derive"
        response = app.post(f"/v1/{operation}", data=body(runtime, arguments), content_type="application/cbor")
        assert response.status_code == HTTPStatus.OK
        return codec.decode(response.data)

    monkeypatch.setattr(Client, "invoke", invoke)
    monkeypatch.setattr(native_cli, "require_protected", lambda _: None)
    settings = ClientSettings(
        "https://controller.invalid",
        "fixture-ca",
        "fixture-cert",
        "fixture-key",
        runtime.access.scope.tenant,
        runtime.access.scope.identity,
        runtime.access.grant,
        runtime.access.task,
        runtime.access.epoch,
        runtime.access.policy,
    )
    client_path, review_path, output_path = (tmp_path / name for name in ("client.json", "review.json", "receipt.json"))
    client_path.write_text(json.dumps(as_data(settings)))
    review_path.write_text(
        json.dumps(
            {
                "reason": "Explicit synthetic selections",
                "children": [
                    {
                        "destination": alias.name,
                        "ref": child.ref,
                        "selections": [
                            {"sources": list(selection.sources), "domain": selection.entry.domain, "value": selection.entry.value}
                            for selection in child.selections
                        ],
                    }
                    for alias, child in zip(aliases, outputs, strict=True)
                ],
            }
        )
    )
    operation = str(uuid4())
    assert (
        cli.main(
            [
                "native",
                "ref",
                "split",
                "--client",
                str(client_path),
                "--input",
                str(review_path),
                "--operation",
                operation,
                "--expected",
                expected,
                "--output",
                str(output_path),
            ]
        )
        == 0
    )
    assert json.loads(output_path.read_text())["operation"] == operation
    assert all(len(child.service.history(child.access, "main")) == 1 for child in outputs)
