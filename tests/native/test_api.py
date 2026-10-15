"""
Exercise the consolidated controller against real storage while keeping transport identity injection explicit in tests.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from uuid import uuid4

from witful.native import codec, domains
from witful.native.api.admission import Admission
from witful.native.api.builder import Builder

from tests.native.runtime import lesson

if TYPE_CHECKING:
    from tests.native.runtime import Runtime


def body(runtime: Runtime, arguments: object) -> bytes:
    """
    Encode the public request contract without allowing a caller to choose its authenticated certificate identity.

    Args:
        runtime (Runtime): Synthetic service grant.
        arguments (object): Operation-owned closed argument map.

    Returns:
        bytes: Native CBOR request.
    """
    access = runtime.access
    return codec.encode(
        {
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
    )


def test_api_domain_and_metrics_share_one_application(runtime: Runtime) -> None:
    """
    Execute a durable append through the same application that exposes private operational snapshots.

    Args:
        runtime (Runtime): Real backend fixture.

    Returns:
        None: API results, admission accounting and readiness separation remain consistent.
    """
    admission = Admission(1)
    app = Builder(runtime.service, admission, lambda: False, lambda: runtime.access.subject).build()
    client = app.test_client()
    response = client.post(
        "/v1/append",
        data=body(
            runtime,
            {
                "operation": str(uuid4()),
                "ref": "main",
                "expected": None,
                "entries": [domains.encode(lesson())],
            },
        ),
        content_type="application/cbor",
    )
    assert response.status_code == HTTPStatus.OK
    assert response.headers["Cache-Control"] == "no-store"
    receipt = codec.decode(response.data)
    assert isinstance(receipt, dict) and receipt["outcome"] == "durable"
    assert client.get("/live").status_code == HTTPStatus.OK
    assert client.get("/ready").status_code == HTTPStatus.SERVICE_UNAVAILABLE
    status = client.get("/status").get_json()
    assert status["in_flight"] == 0 and status["completed"] == 1 and status["queue_size"] == 0
    metrics = client.get("/metrics").data
    assert b"witful_native_in_flight 0" in metrics
    assert b"canary" not in metrics and runtime.access.scope.tenant.encode() not in metrics
    assert admission.acquire()
    refused = client.post("/v1/read", data=b"not decoded while saturated", content_type="application/cbor")
    assert refused.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    admission.release(0.0, False)
    admission.stop()
    admission.stop()
    assert client.get("/status").get_json()["status"] == "draining"


def test_forged_headers_cannot_authenticate(runtime: Runtime) -> None:
    """
    Reject caller-supplied identity headers when an actual verified TLS socket is absent.

    Args:
        runtime (Runtime): Real storage service with the production authentication boundary.

    Returns:
        None: No durable request or key operation occurs under a forged forwarded identity.
    """
    app = Builder(runtime.service, Admission(1), lambda: True).build()
    response = app.test_client().post(
        "/v1/append",
        data=body(
            runtime,
            {
                "operation": str(uuid4()),
                "ref": "main",
                "expected": None,
                "entries": [domains.encode(lesson())],
            },
        ),
        content_type="application/cbor",
        headers={"X-Client-Cert-Fingerprint": runtime.access.subject, "X-Forwarded-Client-Cert": runtime.access.subject},
    )
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert runtime.service.store.head(runtime.access.scope).generation == 0
    assert response.data == codec.encode({"code": "denied"})


def test_invalid_requests_are_bounded_and_redacted(runtime: Runtime) -> None:
    """
    Keep malformed private input out of HTTP errors and release admission after failures.

    Args:
        runtime (Runtime): Real service fixture.

    Returns:
        None: Fixed diagnostics contain neither private text nor exception details.
    """
    admission = Admission(1)
    app = Builder(runtime.service, admission, lambda: True, lambda: runtime.access.subject).build()
    client = app.test_client()
    for payload in (b"sensitive-invalid-content", codec.encode({"extra": "sensitive-invalid-content"})):
        response = client.post("/v1/read", data=payload, content_type="application/cbor")
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert b"sensitive" not in response.data
    assert admission.snapshot()["in_flight"] == 0
    assert admission.snapshot()["failures"] == 2
