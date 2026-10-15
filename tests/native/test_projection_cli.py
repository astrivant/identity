"""
Exercise recursive projection commands through the actual controller API and both native backends.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING
from uuid import uuid4

from attrs import evolve
from witful import cli
from witful.knowledge.contracts import as_data
from witful.native import cli as native_cli
from witful.native import codec
from witful.native.api.admission import Admission
from witful.native.api.builder import Builder
from witful.native.client import Client, ClientSettings
from witful.native.context import Context
from witful.native.models import parse
from witful.native.projection import cli as scheduler
from witful.native.projection.models import PERMIT
from witful.native.wire import binary, mapping

from tests.native.projection import configured
from tests.native.requests import body
from tests.native.runtime import lesson

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from tests.native.database import Databases
    from tests.native.runtime import Runtime


def test_projection_commands_retain_required_gate_and_seal_probe(
    runtime: Runtime,
    databases: Databases,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Verify incomplete exit status, explicit scheduling deferral and a permit-only readiness export through real parser/API/storage paths.

    Args:
        runtime (Runtime): Real native backend.
        databases (Databases): Synthetic grant administrator.
        tmp_path (Path): Disposable client settings and encrypted probe output.
        monkeypatch (pytest.MonkeyPatch): Bridge only transport and synthetic temporary-storage policy.
        capsys (pytest.CaptureFixture[str]): Observe bounded command output.

    Returns:
        None: Local durability cannot close a remote-required operation and probes disclose no domain plaintext.
    """
    service = configured(runtime, databases)
    operation = str(uuid4())
    service.append(runtime.access, operation, "main", None, (lesson(),))
    service = evolve(service, projection=evolve(service.projection, mode="manual"))
    app = Builder(service, Admission(1), lambda: True, lambda: runtime.access.subject).build().test_client()

    def invoke(client: Client, operation: str, arguments: object) -> object:
        """
        Pass actual CLI wire requests through the consolidated app without claiming this bridge tests TLS.

        Args:
            client (Client): Actual parsed client configuration.
            operation (str): Selected package-owned endpoint.
            arguments (object): Actual command arguments.

        Returns:
            object: Authenticated real controller response.
        """
        assert client.settings.identity == runtime.access.scope.identity
        response = app.post(f"/v1/{operation}", data=body(runtime, arguments), content_type="application/cbor")
        assert response.status_code == HTTPStatus.OK
        return codec.decode(response.data)

    monkeypatch.setattr(Client, "invoke", invoke)
    monkeypatch.setattr(native_cli, "require_protected", lambda _: None)
    monkeypatch.setattr(scheduler, "require_protected", lambda _: None)
    access = runtime.access
    settings = ClientSettings(
        "https://controller.invalid",
        "ca",
        "certificate",
        "key",
        access.scope.tenant,
        access.scope.identity,
        access.grant,
        access.task,
        access.epoch,
        access.policy,
    )
    path = tmp_path / "client.json"
    path.write_text(json.dumps(as_data(settings)))
    assert cli.main(["native", "projection", "check", "--client", str(path), "--operation", operation]) == 1
    assert json.loads(capsys.readouterr().out)["complete"] is False
    assert cli.main(["native", "projection", "tick", "--client", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["targets"][0]["state"] == "manual"
    output = tmp_path / "probe.cbor"
    assert cli.main(["native", "projection", "probe", "--client", str(path), "--output", str(output)]) == 0
    package = mapping(codec.decode(output.read_bytes()), {"context", "sealed"})
    context = parse(package["context"], Context)
    assert context.kind == PERMIT and context.tenant == access.scope.tenant
    assert service.keys(access).open(context, binary(package["sealed"])) == {"probe": 1}
    assert b"synthetic-native-canary" not in output.read_bytes()
