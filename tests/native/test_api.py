"""
Exercise the consolidated controller against real storage while keeping transport identity injection explicit in tests.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from threading import Event
from typing import TYPE_CHECKING
from uuid import uuid4

from witful.native import codec, domains
from witful.native.api.admission import Admission
from witful.native.api.builder import Builder
from witful.native.service import Service

from tests.native.requests import body
from tests.native.runtime import branches, lesson

if TYPE_CHECKING:
    import pytest
    from witful.native.authority import Access
    from witful.native.domains import Entry

    from tests.native.runtime import Runtime


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


def test_reviewed_merge_api_retains_candidate(runtime: Runtime) -> None:
    """
    Exercise the authenticated wire mapping for an explicit branch review.

    Args:
        runtime (Runtime): Real supported backend and current grant.

    Returns:
        None: The review route preserves the candidate and rejects a stale target.
    """
    target, candidate = branches(runtime)
    original = runtime.service.history(runtime.access, "candidate")
    client = Builder(runtime.service, Admission(1), lambda: True, lambda: runtime.access.subject).build().test_client()
    arguments = {
        "operation": str(uuid4()),
        "target": "main",
        "candidate": "candidate",
        "expected": target,
        "reviewed": candidate,
        "reason": "Reviewed without automatic journal union",
        "selections": [],
    }
    response = client.post("/v1/merge", data=body(runtime, arguments), content_type="application/cbor")
    assert response.status_code == HTTPStatus.OK
    assert runtime.service.history(runtime.access, "candidate") == original
    arguments["operation"] = str(uuid4())
    assert client.post("/v1/merge", data=body(runtime, arguments), content_type="application/cbor").status_code == HTTPStatus.CONFLICT


def test_recovery_and_status_survive_execution_saturation(runtime: Runtime, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Hold actual domain work until recovery and operational calls have completed through the same application.

    Args:
        runtime (Runtime): Real Git or PostgreSQL service with an independent current grant.
        monkeypatch (pytest.MonkeyPatch): Insert an event barrier before the ordinary read acquires domain resources.

    Returns:
        None: Reserved work remains bounded, recovery succeeds, and every owned request is released without sleeps.
    """
    service, access = runtime.service, runtime.access
    service.append(access, str(uuid4()), "main", None, (lesson(),))
    record = service.history(access, "main")[0][0].id
    entered, resume = Event(), Event()
    original = Service.read

    def blocked(self: Service, selected: Access, revision: str) -> Entry:
        """
        Hold one admitted execution request without holding the authority or storage lock.

        Args:
            self (Service): Real service instance.
            selected (Access): Current synthetic grant.
            revision (str): Existing record UUID.

        Returns:
            Entry: Actual service result after the test releases execution.
        """
        entered.set()
        assert resume.wait(15), "Execution barrier was not released"
        return original(self, selected, revision)

    monkeypatch.setattr(Service, "read", blocked)
    admission = Admission(1, recovery_limit=1)
    app = Builder(service, admission, lambda: True, lambda: access.subject).build()
    client = app.test_client()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(app.test_client().post, "/v1/read", data=body(runtime, {"record": record}), content_type="application/cbor")
        try:
            assert entered.wait(10), "Ordinary read did not reach its barrier"
            assert client.get("/status").get_json()["in_flight"] == 1
            assert b"witful_native_recovery_in_flight 0" in client.get("/metrics").data
            assert client.post("/v1/read", data=b"not decoded").status_code == HTTPStatus.SERVICE_UNAVAILABLE
            response = client.post("/v1/recover", data=body(runtime, {}), content_type="application/cbor")
            assert response.status_code == HTTPStatus.OK
            recovered = codec.decode(response.data)
            assert isinstance(recovered, dict) and recovered["generation"] == 1
            # Recovery has its own finite quota, and shutdown closes both admission classes.
            assert admission.acquire(recovery=True)
            try:
                assert client.post("/v1/recover", data=b"not decoded").status_code == HTTPStatus.SERVICE_UNAVAILABLE
                assert client.get("/status").get_json()["recovery_in_flight"] == 1
            finally:
                admission.release(0.0, False, recovery=True)
            admission.stop()
            assert client.post("/v1/recover", data=b"not decoded").status_code == HTTPStatus.SERVICE_UNAVAILABLE
        finally:
            resume.set()
        assert pending.result(timeout=10).status_code == HTTPStatus.OK
    assert admission.snapshot()["in_flight"] == 0
    assert admission.snapshot()["recovery_in_flight"] == 0
