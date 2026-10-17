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

from witful.codegraph.api import routes as codegraph_routes
from witful.exceptions import NativeError
from witful.intent.api import routes as intent_routes
from witful.native import codec
from witful.native.api.archives import routes as archive_routes
from witful.native.api.derivation import routes as derivation_routes
from witful.native.api.maintenance import routes as maintenance_routes
from witful.native.api.projection import routes as projection_routes
from witful.native.api.records import routes
from witful.native.api.sharing import routes as sharing_routes

if TYPE_CHECKING:
    from collections.abc import Callable

    from witful.codegraph.models import Enrollment
    from witful.native.api.admission import Admission
    from witful.native.config import ArchivePath, DerivationTarget, ExportRecipient
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
        destinations (tuple[Service, ...]): Explicit inactive migration targets from verified deployment configuration.
        archives (tuple[ArchivePath, ...]): Explicit identity-bound filesystem locations from signed settings.
        derivations (tuple[DerivationTarget, ...]): Independently authorized fork/split target aliases.
        recipients (tuple[ExportRecipient, ...]): Explicit identity-bound public recipients from signed settings.
        codegraphs (tuple[Enrollment, ...]): Optional protected repository extensions from signed settings.
    """

    service: Service
    admission: Admission
    readiness: Callable[[], bool]
    authenticate: Callable[[], str] = peer_fingerprint
    destinations: tuple[Service, ...] = ()
    archives: tuple[ArchivePath, ...] = ()
    derivations: tuple[DerivationTarget, ...] = ()
    recipients: tuple[ExportRecipient, ...] = ()
    codegraphs: tuple[Enrollment, ...] = ()

    def __attrs_post_init__(self) -> None:
        """
        Keep generic-route denial aligned with the exact enrolled graph scopes.

        Returns:
            None: Every configured graph scope is fenced from generic HTTP operations.
        """
        if set(self.service.graph_scopes) != {(item.tenant, item.extension) for item in self.codegraphs}:
            raise NativeError("invalid")

    def build(self) -> Flask:
        """
        Register central boundaries and domain blueprints on exactly one Flask application.

        Returns:
            Flask: Complete application without starting a listener or background thread.
        """
        return Boundary(
            "witful.native",
            self.service.budget.bytes,
            self.admission,
            self.readiness,
            (
                routes(self.service, self.authenticate),
                codegraph_routes(self.service, self.authenticate, self.codegraphs),
                intent_routes(self.service, self.authenticate, self.codegraphs),
                projection_routes(self.service, self.authenticate),
                maintenance_routes(self.service, self.authenticate, self.destinations),
                archive_routes(self.service, self.authenticate, self.archives),
                sharing_routes(self.service, self.authenticate, self.recipients),
                derivation_routes(self.service, self.authenticate, self.destinations, self.derivations),
            ),
            self.authenticate,
        ).build()


@frozen
class Boundary:
    """
    Consolidate transport, operational endpoints and error/admission ownership for each independently deployed role.

    Attributes:
        name (str): Fixed application identity.
        bytes (int): Maximum request body bytes before decoding.
        admission (Admission): Owned request lifecycle and local metrics.
        readiness (Callable[[], bool]): Role-specific dependency readiness.
        blueprints (tuple[Blueprint, ...]): Injected domain routes assembled into one application.
        authenticate (Callable[[], str]): Verify listener-owned peer identity before quota-sensitive work.
    """

    name: str
    bytes: int
    admission: Admission
    readiness: Callable[[], bool]
    blueprints: tuple[Blueprint, ...]
    authenticate: Callable[[], str] = peer_fingerprint

    def build(self) -> Flask:
        """
        Build one application with shared error handling and operational boundaries.

        Returns:
            Flask: Complete role-specific app without starting listeners or background work.
        """
        app = Flask(self.name)
        app.config.update(MAX_CONTENT_LENGTH=self.bytes, DEBUG=False, TESTING=False)
        for blueprint in self.blueprints:
            app.register_blueprint(blueprint)
        operational = Blueprint("native_operations", __name__)

        @app.before_request
        def admit() -> Response | None:
            """
            Bound application-owned work before reading or decoding a private request.

            Returns:
                Response | None: Immediate overload response or admission for normal routing.
            """
            if request.path.startswith("/v1/"):
                self.authenticate()
                recovery = request.path in {"/v1/recover", "/v1/migration-abort"}
                if not self.admission.acquire(recovery):
                    return Response(status=HTTPStatus.SERVICE_UNAVAILABLE)
                g.native_recovery = recovery
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
                self.admission.release(
                    time.monotonic() - started, response.status_code >= HTTPStatus.BAD_REQUEST, bool(g.pop("native_recovery", False))
                )
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
                "diverged": HTTPStatus.CONFLICT,
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
                for name in (
                    "queue_size",
                    "in_flight",
                    "admission_limit",
                    "recovery_limit",
                    "recovery_in_flight",
                    "completed",
                    "failures",
                    "rejected",
                    "request_seconds",
                )
            ]
            dependencies = snapshot["dependency_seconds"]
            assert isinstance(dependencies, dict)
            lines.extend(f'witful_native_dependency_seconds{{dependency="{name}"}} {value}' for name, value in sorted(dependencies.items()))
            return Response("\n".join(lines) + "\n", mimetype="text/plain")

        app.register_blueprint(operational)
        return app
