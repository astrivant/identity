"""
Replay contracts produced by the native client against its real composed Flask provider.
"""

from __future__ import annotations

import os
import ssl
from contextlib import contextmanager
from http import HTTPStatus
from http.client import HTTPConnection
from threading import Thread
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from pact import Pact, Verifier
from werkzeug.serving import make_server
from witful.exceptions import NativeError
from witful.native import client as transport
from witful.native import codec, domains
from witful.native.api.admission import Admission
from witful.native.api.builder import Builder
from witful.native.client import Client, ClientSettings

from tests.native.runtime import lesson

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from flask import Flask, Response

    from tests.native.runtime import Runtime


@contextmanager
def serve(app: Flask) -> Iterator[str]:
    """
    Own one loopback provider listener and join its thread on every verification outcome.

    Args:
        app (Flask): Real application with synthetic transport identity and custody.

    Yields:
        str: Ephemeral HTTP origin; existing native transport tests independently verify mTLS.
    """
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def loopback(host: str, port: int, *, context: ssl.SSLContext, timeout: int) -> HTTPConnection:
    """
    Substitute only the socket layer while exercising the production client's encoding and error handling.

    Args:
        host (str): Pact loopback listener.
        port (int): Random mock server port.
        context (ssl.SSLContext): Client-created TLS configuration, unused by this HTTP-only test transport.
        timeout (int): Production client timeout.

    Returns:
        HTTPConnection: Bounded synthetic connection with no external credentials.
    """
    assert host == "127.0.0.1" and context.minimum_version == ssl.TLSVersion.TLSv1_3
    return HTTPConnection(host, port, timeout=timeout)


def ignore_chain(self: ssl.SSLContext, certfile: str, keyfile: str) -> None:
    """
    Avoid loading credentials in the explicitly plaintext test transport.

    Args:
        self (ssl.SSLContext): Test client context.
        certfile (str): Unused synthetic certificate location.
        keyfile (str): Unused synthetic key location.

    Returns:
        None: Actual certificate handling remains covered by native mTLS integration tests.
    """


@pytest.mark.parametrize("operation", ["history", "read", "codegraph-query", "intent-query", "search"])
def test_consumer_and_composed_provider(runtime: Runtime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    """
    Verify the same consumer-generated Pact against real Git/PostgreSQL services and shared feature routes.

    Args:
        runtime (Runtime): Real storage, authorization and synthetic cryptographic custody.
        tmp_path (Path): Isolated Pact output directory.
        monkeypatch (pytest.MonkeyPatch): Replace only client sockets and disable Pact telemetry.
        operation (str): Native or extension boundary selected for this interaction.

    Returns:
        None: Both consumer encoding/decoding and provider playback satisfy the declared contract.
    """
    monkeypatch.setenv("PACT_DO_NOT_TRACK", "1")
    access = runtime.access
    arguments: object = {"ref": "main"}
    expected: object = {"code": "denied"}
    status = HTTPStatus.FORBIDDEN
    if operation == "read":
        status = HTTPStatus.OK
        runtime.service.append(access, str(uuid4()), "main", None, (lesson("contract-record"),))
        record = runtime.service.history(access, "main")[0][0].id
        arguments, expected = {"record": record}, domains.encode(lesson("contract-record"))
    elif operation.endswith("-query"):
        arguments, expected, status = {}, {"code": "denied"}, HTTPStatus.FORBIDDEN
    elif operation == "search":
        arguments, expected, status = {"unexpected": True}, {"code": "invalid"}, HTTPStatus.BAD_REQUEST
    payload = {
        "access": {
            "tenant": access.scope.tenant,
            "identity": access.scope.identity,
            "grant": access.grant,
            "task": access.task,
            "epoch": access.epoch,
            "policy": access.policy,
        },
        "arguments": arguments,
    }
    pact = Pact("witful-native-client", f"witful-{type(runtime.service.store).__name__.lower()}-{operation}").with_specification("V4")
    interaction = pact.upon_receiving(f"{operation} preserves the native binary contract")
    interaction.with_request("POST", f"/v1/{operation}").with_binary_body(codec.encode(payload), "application/cbor")
    interaction.will_respond_with(status).with_binary_body(codec.encode(expected), "application/cbor")

    # No provider mock is used for playback: the actual builder composes native, graph and intent routes.
    with pact.serve(addr="127.0.0.1") as mock, monkeypatch.context() as patch:
        patch.setattr(transport, "HTTPSConnection", loopback)
        patch.setattr(ssl.SSLContext, "load_cert_chain", ignore_chain)
        settings = ClientSettings(
            f"https://127.0.0.1:{mock.port}",
            ssl.get_default_verify_paths().cafile or "",
            "synthetic",
            "synthetic",
            access.scope.tenant,
            access.scope.identity,
            access.grant,
            access.task,
            access.epoch,
            access.policy,
        )
        if status == HTTPStatus.OK:
            assert Client(settings).invoke(operation, arguments) == expected
        else:
            with pytest.raises(NativeError) as failure:
                Client(settings).invoke(operation, arguments)
            assert isinstance(expected, dict) and failure.value.code == expected["code"]
    pact_directory = tmp_path / "pacts"
    pact_directory.mkdir()
    pact.write_file(pact_directory)
    assert len(list(pact_directory.glob("*.json"))) == 1
    app = Builder(runtime.service, Admission(4), lambda: True, lambda: access.subject).build()
    with serve(app) as url:
        Verifier(f"witful-{type(runtime.service.store).__name__.lower()}-{operation}", host="127.0.0.1").add_transport(url=url).add_source(
            pact_directory
        ).verify()

    # A provider-only wire regression must fail even when the consumer test still passes.
    app = Builder(runtime.service, Admission(4), lambda: True, lambda: access.subject).build()

    @app.after_request
    def corrupt(response: Response) -> Response:
        """
        Deliberately break the binary response to prove the verifier detects provider drift.

        Args:
            response (Response): Actual provider response.

        Returns:
            Response: Mutated test-only payload.
        """
        response.set_data(codec.encode({"changed": True}))
        return response

    with serve(app) as url, pytest.raises(RuntimeError, match="Failed to execute verifier"):
        Verifier(f"witful-{type(runtime.service.store).__name__.lower()}-{operation}", host="127.0.0.1").add_transport(url=url).add_source(
            pact_directory
        ).verify()

    # Retain only synthetic Pact files when CI requests an explicit evidence directory.
    if destination := os.environ.get("WITFUL_PACT_OUTPUT"):
        pact.write_file(destination)
