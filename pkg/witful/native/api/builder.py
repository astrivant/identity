"""
Build one Flask application with central mTLS authentication, bounded admission and private operational endpoints.
"""

from __future__ import annotations

import hashlib
import ssl
import time
from http import HTTPStatus
from typing import TYPE_CHECKING

from attrs import frozen
from flask import Blueprint, Flask, Response, g, request
from werkzeug.exceptions import HTTPException

from witful.exceptions import NativeError
from witful.native import codec
from witful.native.api.records import routes

if TYPE_CHECKING:
    from collections.abc import Callable

    from witful.native.api.admission import Admission
    from witful.native.service import Service

__all__ = ["Builder", "peer_fingerprint"]


def peer_fingerprint() -> str:
    """
    Resolve only an actual verified server-side TLS socket supplied by Gunicorn.

    Returns:
        str: SHA-256 of the verified client certificate; forwarded headers never establish identity.
    """
    peer: object = request.environ.get("gunicorn.socket")
    if not isinstance(peer, ssl.SSLSocket) or not peer.server_side or peer.context.verify_mode != ssl.CERT_REQUIRED:
        raise NativeError("denied")
    certificate = peer.getpeercert(binary_form=True)
    if not certificate or peer.version() != "TLSv1.3":
        raise NativeError("denied")
    return hashlib.sha256(certificate).hexdigest()


@frozen
class Builder:
    """
    Compose immutable service dependencies into one application; the runtime owns listeners and shutdown.

    Attributes:
        service (Service): Native storage service.
        admission (Admission): Shared worker-local ownership and metrics.
        readiness (Callable[[], bool]): Bounded protected-storage, authority and key-health check.
        authenticate (Callable[[], str]): Trusted transport boundary; the production default requires verified mutual TLS.
    """

    service: Service
    admission: Admission
    readiness: Callable[[], bool]
    authenticate: Callable[[], str] = peer_fingerprint

    def build(self) -> Flask:
        """
        Register central boundaries and domain blueprints on exactly one Flask application.

        Returns:
            Flask: Complete application without starting a listener or background thread.
        """
        app = Flask("witful.native")
        app.config.update(MAX_CONTENT_LENGTH=self.service.budget.bytes, DEBUG=False, TESTING=False)
        app.register_blueprint(routes(self.service, self.authenticate))
        operational = Blueprint("native_operations", __name__)

        @app.before_request
        def admit() -> Response | None:
            """
            Bound application-owned work before reading or decoding a private request.

            Returns:
                Response | None: Immediate overload response or admission for normal routing.
            """
            if request.path.startswith("/v1/"):
                if not self.admission.acquire():
                    return Response(status=HTTPStatus.SERVICE_UNAVAILABLE)
                g.native_started = time.monotonic()
            return None

        @app.after_request
        def secure(response: Response) -> Response:
            """
            Prevent storage of private responses in intermediaries and clear ownership after response construction.

            Args:
                response (Response): Complete bounded response.

            Returns:
                Response: Response with cache prevention and sensitive browser features disabled.
            """
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            started: object = g.pop("native_started", None)
            if isinstance(started, float):
                self.admission.release(time.monotonic() - started, response.status_code >= HTTPStatus.BAD_REQUEST)
            return response

        @app.errorhandler(Exception)
        def error(failure: Exception) -> Response:
            """
            Contain diagnostics at the public boundary without serializing exceptions, SQL parameters or private request values.

            Args:
                failure (Exception): Domain, HTTP or unexpected application failure.

            Returns:
                Response: Fixed bounded error code; unexpected failures remain visible as server failures.
            """
            statuses = {
                "denied": HTTPStatus.FORBIDDEN,
                "invalid": HTTPStatus.BAD_REQUEST,
                "conflict": HTTPStatus.CONFLICT,
                "incomplete": HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "unsupported": HTTPStatus.UNPROCESSABLE_ENTITY,
                "unknown": HTTPStatus.SERVICE_UNAVAILABLE,
                "unavailable": HTTPStatus.SERVICE_UNAVAILABLE,
            }
            code = failure.code if isinstance(failure, NativeError) else "unavailable"
            status = statuses[code] if isinstance(failure, NativeError) else HTTPStatus.INTERNAL_SERVER_ERROR
            if isinstance(failure, HTTPException) and failure.code is not None:
                status = HTTPStatus(failure.code)
            return Response(codec.encode({"code": code}), status=status, mimetype="application/cbor")

        @operational.get("/live")
        def live() -> Response:
            """
            Report process liveness without restarting a healthy worker for an upstream outage.

            Returns:
                Response: Successful live status.
            """
            return Response("live\n", mimetype="text/plain")

        @operational.get("/ready")
        def ready() -> Response:
            """
            Check actual admission dependencies independently of liveness.

            Returns:
                Response: Ready only when protected storage, current authority and key service are available.
            """
            result = self.readiness() and not self.admission.draining
            return Response(
                "ready\n" if result else "unavailable\n",
                status=HTTPStatus.OK if result else HTTPStatus.SERVICE_UNAVAILABLE,
                mimetype="text/plain",
            )

        @operational.get("/status")
        def status() -> dict[str, object]:
            """
            Expose bounded operational state without consulting external dependencies.

            Returns:
                dict[str, object]: Local queue, owned work, status and dependency timing snapshot.
            """
            return self.admission.snapshot()

        @operational.get("/metrics")
        def metrics() -> Response:
            """
            Render fixed-label operational metrics from the same application.

            Returns:
                Response: Prometheus-compatible local worker counters and gauges.
            """
            snapshot = self.admission.snapshot()
            lines = [
                f"witful_native_{name} {snapshot[name]}"
                for name in ("queue_size", "in_flight", "admission_limit", "completed", "failures", "rejected", "request_seconds")
            ]
            dependencies = snapshot["dependency_seconds"]
            assert isinstance(dependencies, dict)
            lines.extend(f'witful_native_dependency_seconds{{dependency="{name}"}} {value}' for name, value in sorted(dependencies.items()))
            return Response("\n".join(lines) + "\n", mimetype="text/plain")

        app.register_blueprint(operational)
        return app
