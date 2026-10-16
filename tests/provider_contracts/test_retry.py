"""
Exercise the real SDK retry transport against bounded loopback failures with deterministic waits.
"""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import TYPE_CHECKING

import pytest
from github import Github, GithubException
from github.GithubException import RateLimitExceededExceedsMaxWait
from github.GithubRetry import GithubRetry
from provider_contracts.refresh import encoded, github_retry
from requests import Session
from requests.exceptions import ConnectionError, RetryError

if TYPE_CHECKING:
    from pytest import MonkeyPatch
    from requests import PreparedRequest, Response


class FixedDatetime(datetime):
    """
    Freeze the SDK's UTC reset calculation without depending on test execution speed.
    """

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> FixedDatetime:
        """
        Return the same instant used by synthetic reset and HTTP-date headers.

        Args:
            tz (tzinfo | None): Timezone selected by the SDK.

        Returns:
            FixedDatetime: The fixed test clock in the requested timezone.
        """
        return cls.fromtimestamp(1_700_000_000, tz)


@pytest.mark.parametrize(
    ("status", "message", "headers", "failures", "expected_waits", "error"),
    [
        (HTTPStatus.FORBIDDEN, "API rate limit exceeded", {"Retry-After": "5"}, 1, [5.5], None),
        (HTTPStatus.FORBIDDEN, "API rate limit exceeded", {"Retry-After": "0"}, 1, [0.5], None),
        (
            HTTPStatus.FORBIDDEN,
            "API rate limit exceeded",
            {"Retry-After": "5", "X-RateLimit-Reset": "1700000200"},
            1,
            [5.5],
            None,
        ),
        (
            HTTPStatus.TOO_MANY_REQUESTS,
            "You have exceeded a secondary rate limit.",
            {"Retry-After": "Tue, 14 Nov 2023 22:13:30 GMT"},
            1,
            [10.5],
            None,
        ),
        (
            HTTPStatus.FORBIDDEN,
            "API rate limit exceeded",
            {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000100"},
            1,
            [101.5],
            None,
        ),
        (HTTPStatus.FORBIDDEN, "You have exceeded a secondary rate limit.", {}, 1, [60.5], None),
        (HTTPStatus.SERVICE_UNAVAILABLE, "Temporarily unavailable", {}, 2, [0.5, 2.5], None),
        (HTTPStatus.FORBIDDEN, "Resource not accessible by integration", {}, 1, [], GithubException),
        (HTTPStatus.UNAUTHORIZED, "Bad credentials", {}, 1, [], GithubException),
        (HTTPStatus.FORBIDDEN, "API rate limit exceeded", {"Retry-After": "121"}, 1, [], ConnectionError),
        (
            HTTPStatus.FORBIDDEN,
            "API rate limit exceeded",
            {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000200"},
            1,
            [],
            RateLimitExceededExceedsMaxWait,
        ),
        (HTTPStatus.FORBIDDEN, "API rate limit exceeded", {"Retry-After": "2"}, 3, [2.5, 2.5], RetryError),
    ],
)
def test_sdk_header_delays_and_bounded_retries(
    monkeypatch: MonkeyPatch,
    status: HTTPStatus,
    message: str,
    headers: dict[str, str],
    failures: int,
    expected_waits: list[float],
    error: type[Exception] | None,
) -> None:
    """
    Verify header precedence, additive jitter, finite attempts and permanent-failure handling through real HTTP.

    Args:
        monkeypatch (MonkeyPatch): Freeze clock/jitter, capture sleep and refuse external transport.
        status (HTTPStatus): Synthetic failure status.
        message (str): SDK-recognized rate-limit message or permanent error.
        headers (dict[str, str]): Server-directed timing headers.
        failures (int): Failed responses before the server offers a successful result.
        expected_waits (list[float]): Exact sleep sequence after SDK classification and jitter.
        error (type[Exception] | None): Expected terminal exception, or success.

    Returns:
        None: Only permitted retries occur, and all server/client resources are closed.
    """
    waits: list[float] = []
    requests: list[str] = []
    monkeypatch.setattr(GithubRetry, "_GithubRetry__datetime", FixedDatetime)
    monkeypatch.setattr("urllib3.util.retry.time.time", lambda: FixedDatetime.now(UTC).timestamp())
    monkeypatch.setattr("provider_contracts.refresh.time.sleep", waits.append)
    monkeypatch.setattr("provider_contracts.refresh.random.uniform", lambda low, high: (low + high) / 2)

    class Handler(BaseHTTPRequestHandler):
        """
        Supply a deterministic sequence of failures followed by a minimal repository response.
        """

        def do_GET(self) -> None:
            """
            Serve one request without accepting credentials or undeclared paths.

            Returns:
                None: A bounded JSON response is written to the loopback socket.
            """
            requests.append(self.path)
            failed = len(requests) <= failures
            body = encoded({"message": message} if failed else {"full_name": "example/project"})
            self.send_response(status if failed else HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            if failed:
                for name, value in headers.items():
                    self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            """
            Keep synthetic HTTP traffic out of test output.

            Args:
                format (str): Standard server format, unused.
                *args (object): Standard log arguments, unused.

            Returns:
                None: Nothing is logged.
            """

    server = HTTPServer(("127.0.0.1", 0), Handler)
    host = f"http://127.0.0.1:{server.server_port}"
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    send = Session.send

    def local_only(session: Session, request: PreparedRequest, **kwargs: object) -> Response:
        """
        Preserve the actual transport adapter while refusing external requests and credentials.

        Args:
            session (Session): SDK-owned session.
            request (PreparedRequest): Prepared metadata request.
            **kwargs (object): Unchanged transport arguments.

        Returns:
            Response: Response from the loopback server through the real retry adapter.
        """
        assert request.url == host + "/repos/example/project"
        assert request.method == "GET"
        assert "Authorization" not in request.headers
        return send(session, request, **kwargs)

    monkeypatch.setattr(Session, "send", local_only)
    thread.start()
    try:
        with Github(base_url=host, retry=github_retry(), timeout=1) as client:
            if error is None:
                assert client.get_repo("example/project").full_name == "example/project"
            else:
                with pytest.raises(error) as caught:
                    client.get_repo("example/project")
                if error is ConnectionError:
                    # Requests wraps the adapter's TimeoutError; preserve its actionable budget diagnostic.
                    assert "120-second wait budget" in str(caught.value)
        assert waits == expected_waits
        assert len(requests) == len(expected_waits) + 1
        assert set(requests) == {"/repos/example/project"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()
