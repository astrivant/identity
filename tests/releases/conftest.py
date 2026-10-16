"""
Serve vendor-schema-validated release responses to the real GitHub SDK over loopback HTTP.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from attrs import define, field
from github import Github
from requests import Session

from tests.support.provider_contracts import response_body

if TYPE_CHECKING:
    from collections.abc import Iterator

    from github.Repository import Repository
    from requests import PreparedRequest, Response

BASE = "a" * 40
SOURCE = "b" * 40
PREFIX = "/repos/example/project"


@define
class Host:
    """
    Own isolated response state and accepted comment writes for one SDK session.

    Attributes:
        repository (Repository): Real SDK repository pointed at loopback.
        responses (dict[str, object]): Schema-validated responses keyed by path and optional page suffix.
        comments (list[dict[str, object]]): Accepted synthetic issue comments.
        posts (list[str]): Attempted comment bodies.
        seen (list[str]): Requested read paths, including pagination.
        deny (bool): Reject writes with a permanent permission error.
        lose_response (bool): Commit the next comment before dropping its HTTP response.
    """

    repository: Repository
    responses: dict[str, object]
    comments: list[dict[str, object]] = field(factory=list)
    posts: list[str] = field(factory=list)
    seen: list[str] = field(factory=list)
    deny: bool = False
    lose_response: bool = False


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch) -> Iterator[Host]:
    """
    Run an owned HTTP server while refusing external requests and credential forwarding.

    Args:
        monkeypatch (pytest.MonkeyPatch): Isolated transport guard.

    Yields:
        Host: Real SDK with mutable synthetic release scenarios.
    """
    state: Host

    class Handler(BaseHTTPRequestHandler):
        """
        Serve a bounded release fixture and collect actual SDK mutation requests.
        """

        def send_json(self, status: HTTPStatus, value: object, next_page: str = "") -> None:
            """
            Return one framed HTTP response with optional pagination.

            Args:
                status (HTTPStatus): HTTP result.
                value (object): JSON payload.
                next_page (str): Optional next-page URL.

            Returns:
                None: Response body is sent.
            """
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            if next_page:
                self.send_header("Link", f'<{next_page}>; rel="next"')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            """
            Read declared public fixtures and persistent accepted comments.

            Returns:
                None: Unknown paths fail visibly rather than forwarding to GitHub.
            """
            parsed = urlsplit(self.path)
            key = unquote(parsed.path)
            page = parse_qs(parsed.query).get("page", ["1"])[0]
            if page != "1":
                key += ":" + page
            state.seen.append(key)
            if parsed.path.endswith("/issues/5/comments"):
                self.send_json(HTTPStatus.OK, state.comments)
            elif key in state.responses:
                following = f"{url}{parsed.path}?page=2&per_page=100" if key + ":2" in state.responses else ""
                value = state.responses[key]
                if isinstance(value, bytes):
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(len(value)))
                    self.end_headers()
                    self.wfile.write(value)
                else:
                    self.send_json(HTTPStatus.OK, value, following)
            else:
                self.send_json(HTTPStatus.NOT_FOUND, {"message": "Undeclared fixture route"})

        def do_POST(self) -> None:
            """
            Exercise SDK comment creation, denial and accepted-but-unacknowledged writes.

            Returns:
                None: The response reflects the configured transport scenario.
            """
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.posts.append(payload["body"])
            if state.deny:
                self.send_json(HTTPStatus.FORBIDDEN, {"message": "Denied"})
                return
            item = {
                "id": len(state.comments) + 1,
                "body": payload["body"],
                "user": {"login": "github-actions[bot]", "type": "Bot"},
                "html_url": f"https://github.com/example/project/pull/5#issuecomment-{len(state.comments) + 1}",
            }
            rows = response_body("github", "issue_comments", [item])
            assert isinstance(rows, list) and isinstance(rows[0], dict)
            state.comments.append(rows[0])
            if state.lose_response:
                state.lose_response = False
                self.close_connection = True
                self.connection.close()
            else:
                self.send_json(HTTPStatus.CREATED, rows[0])

        def log_message(self, format: str, *args: object) -> None:
            """
            Suppress routine fixture traffic.

            Args:
                format (str): Standard server format.
                *args (object): Standard server parameters.

            Returns:
                None: No fixture request is logged.
            """

    server = HTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{server.server_port}"
    send = Session.send

    def local_only(session: Session, request: PreparedRequest, **options: object) -> Response:
        """
        Retain actual network transport within the owned test listener.

        Args:
            session (Session): SDK-owned HTTP session.
            request (PreparedRequest): Actual SDK request.
            **options (object): Transport parameters.

        Returns:
            Response: Loopback response without external access.
        """
        assert request.url is not None and request.url.startswith(url + "/")
        assert "Authorization" not in request.headers
        return send(session, request, **options)

    monkeypatch.setattr(Session, "send", local_only)
    api = Github(base_url=url, retry=0, timeout=5, per_page=100)
    state = Host(api.get_repo("example/project", lazy=True), {})
    # Vendor examples supply required fields; scenario overrides remain synthetic and are schema checked.
    fixtures: dict[str, tuple[str, object]] = {
        PREFIX: ("project", {"full_name": "example/project", "url": url + PREFIX, "language": None, "source": {"language": None}}),
        PREFIX + "/releases": ("releases", [{"tag_name": "v1.0.0", "draft": False, "prerelease": False}]),
        PREFIX + "/commits/v1.1.0": ("commit", {"sha": SOURCE, "url": url + PREFIX + "/commits/" + SOURCE, "files": []}),
        PREFIX + "/commits/v1.0.0": ("commit", {"sha": BASE, "url": url + PREFIX + "/commits/" + BASE, "files": []}),
        PREFIX + f"/compare/{BASE}...{SOURCE}": (
            "comparison",
            {
                "status": "ahead",
                "total_commits": 1,
                "url": url + PREFIX + f"/compare/{BASE}...{SOURCE}",
                "commits": [{"sha": SOURCE, "url": url + PREFIX + "/commits/" + SOURCE}],
                "files": [],
            },
        ),
        PREFIX + f"/commits/{SOURCE}/pulls": (
            "commit_requests",
            [{"number": 5, "url": url + PREFIX + "/pulls/5", "labels": [], "requested_teams": []}],
        ),
        PREFIX + "/pulls/5": (
            "request",
            {
                "number": 5,
                "url": url + PREFIX + "/pulls/5",
                "issue_url": url + PREFIX + "/issues/5",
                "merged": True,
                "merge_commit_sha": SOURCE,
                "state": "closed",
                "title": "Fix saved-record reporting",
                "user": {"login": "contributor"},
                "base": {"repo": {"full_name": "example/project", "language": None}},
                "labels": [],
                "requested_teams": [],
            },
        ),
    }
    state.responses.update({path: response_body("github", operation, value) for path, (operation, value) in fixtures.items()})
    worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
    worker.start()
    try:
        yield state
    finally:
        api.close()
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()
        assert not worker.is_alive()
