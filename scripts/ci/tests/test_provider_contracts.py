"""
Exercise real SDK HTTP transports against refreshable vendor response contracts.
"""

from __future__ import annotations

import copy
import hashlib
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from threading import Thread
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from github import Github
from openapi_schema_validator import OAS30ReadValidator
from provider_contracts.refresh import DATA, encoded, redact_examples, references, refresh, select
from requests import Response, Session
from witful.delivery.providers.base import object_value
from witful.delivery.tests.test_providers import github_rows, gitlab_rows

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch
    from requests import PreparedRequest


def resolved(document: dict[str, object], value: object) -> dict[str, object]:
    """
    Resolve a response or example reference within the pinned snapshot.

    Args:
        document (dict[str, object]): Complete snapshot reference root.
        value (object): Inline mapping or local reference.

    Returns:
        dict[str, object]: Referenced mapping.
    """
    row = object_value(value)
    if "$ref" in row:
        target: object = document
        for part in str(row["$ref"]).split("/")[1:]:
            target = object_value(target)[part]
        return object_value(target)
    return row


def overlay(example: object, fixture: object) -> object:
    """
    Supply required example fields while retaining deliberate synthetic scenario values.

    Args:
        example (object): Vendor example, used only as structural scaffolding.
        fixture (object): Synthetic coherent project/PR fixture.

    Returns:
        object: New response value without changing either input.
    """
    if isinstance(example, dict) and isinstance(fixture, dict):
        return {**copy.deepcopy(example), **{key: overlay(example.get(key), value) for key, value in fixture.items()}}
    if isinstance(example, list) and isinstance(fixture, list) and example:
        return [overlay(example[0], item) for item in fixture]
    return copy.deepcopy(fixture)


def response_body(provider: str, operation: str, fixture: object) -> object:
    """
    Validate every success payload before the mock server serves it to an SDK.

    Args:
        provider (str): Pinned vendor snapshot name.
        operation (str): Reviewed operation selection.
        fixture (object): Coherent synthetic response overrides.

    Returns:
        object: Response conforming to the selected vendor schema.
    """
    document = object_value(json.loads((DATA / f"{provider}.json").read_text()))
    response = resolved(document, object_value(document["responses"])[operation])
    media = object_value(object_value(response["content"])["application/json"])
    examples = object_value(media.get("examples", {}))
    example = resolved(document, next(iter(examples.values()))).get("value") if examples else None
    value = overlay(example, fixture)
    # OpenAPI 3.0 nullable/readOnly semantics require its response validator, not plain JSON Schema.
    schema = {**object_value(media["schema"]), "components": document["components"]}
    OAS30ReadValidator.check_schema(schema)
    errors = list(OAS30ReadValidator(schema).iter_errors(value))
    assert not errors, [(list(error.path), error.message) for error in errors]
    return value


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_sdk_http_contract(provider: str, monkeypatch: MonkeyPatch) -> None:
    """
    Exercise sockets, SDK parsing, pagination and nested namespaces without SaaS credentials.

    Args:
        provider (str): Backend tested against its pinned response schema.
        monkeypatch (MonkeyPatch): Reject all non-loopback SDK network requests.

    Returns:
        None: Inventory and signature checks retain the expected revision-bound evidence.
    """
    responses: dict[str, object] = {}
    seen: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        """
        Serve only prevalidated GET routes; unexpected paths fail the test.
        """

        def do_GET(self) -> None:
            """
            Respond to one declared route with bounded synthetic pagination.

            Returns:
                None: JSON response written; unknown routes return 404.
            """
            parsed = urlsplit(self.path)
            key = unquote(parsed.path)
            if parse_qs(parsed.query).get("page", ["1"])[0] != "1":
                key += ":" + parse_qs(parsed.query)["page"][0]
            seen.append(key)
            body = encoded(responses.get(key, {"message": "Unexpected mock route"}))
            self.send_response(200 if key in responses else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            if key + ":2" in responses:
                self.send_header("Link", f'<{host}{parsed.path}?page=2&per_page=100>; rel="next"')
                self.send_header("X-Next-Page", "2")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            """
            Keep test HTTP traffic out of CI logs.

            Args:
                format (str): Standard server log format.
                *args (object): Standard server log arguments.

            Returns:
                None: No request contents are logged.
            """

    server = HTTPServer(("127.0.0.1", 0), Handler)
    host = f"http://127.0.0.1:{server.server_port}"
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
    send = Session.send

    def local_only(session: Session, request: PreparedRequest, **kwargs: object) -> Response:
        """
        Preserve real transport while refusing external destinations or credentials.

        Args:
            session (Session): SDK session.
            request (PreparedRequest): SDK-prepared request.
            **kwargs (object): Original transport options.

        Returns:
            Response: Actual loopback HTTP response.
        """
        assert request.url is not None and request.url.startswith(host + "/")
        assert request.method == "GET"
        assert not {"Authorization", "PRIVATE-TOKEN"}.intersection(request.headers)
        return send(session, request, **kwargs)

    monkeypatch.setattr(Session, "send", local_only)
    backend = github_rows(responses, host) if provider == "github" else gitlab_rows(responses, host=host)
    sha = "a" * 40
    if provider == "github":
        base = "/repos/example/project"
        # The vendor repository example omits required nullable language fields.
        responses[base] = {**object_value(responses[base]), "language": None, "source": {"language": None}}
        for key in (base + "/pulls", base + "/pulls/5"):
            value = responses[key]
            items = value if isinstance(value, list) else [value]
            # Empty optional collections avoid unrelated stale team/label examples.
            adjusted = [{**object_value(item), "labels": [], "requested_teams": []} for item in items]
            responses[key] = adjusted if isinstance(value, list) else adjusted[0]
        responses[base + "/commits/" + sha] = {**object_value(responses[base + "/commits/" + sha]), "files": []}
        routes = {
            base: "project",
            base + "/pulls": "requests",
            base + "/pulls:2": "requests",
            base + "/pulls/5": "request",
            base + "/pulls/5/reviews": "reviews",
            base + "/commits/" + sha: "commit",
            base + "/commits/" + sha + "/check-runs": "checks",
            # PyGithub currently uses this legacy alias; schema coverage is explicitly for the documented GET operation.
            base + "/statuses/" + sha: "statuses",
        }
    else:
        base = "/api/v4/projects/group/subgroup/project"
        numeric = "/api/v4/projects/42"
        responses[numeric + "/merge_requests:2"] = []
        routes = {
            base: "project",
            numeric + "/merge_requests": "requests",
            numeric + "/merge_requests:2": "requests",
            numeric + "/merge_requests/5": "request",
            base + "/merge_requests/5/diffs": "diffs",
            numeric + "/repository/commits/" + sha + "/statuses": "statuses",
            base + "/repository/commits/" + sha + "/signature": "signature",
        }

    try:
        for path, operation in routes.items():
            responses[path] = response_body(provider, operation, responses[path])
        assert responses.keys() == routes.keys()
        thread.start()
        assert backend.default_branch() == "main"
        rows = backend.requests()
        assert len(rows) == 1 and rows[0]["headRefOid"] == sha
        assert rows[0]["additions"] == 2 and rows[0]["deletions"] == 1
        assert backend.verified(sha)
        assert set(seen) == set(routes)
    finally:
        if thread.is_alive():
            server.shutdown()
            thread.join(timeout=5)
        server.server_close()
        if isinstance(backend.api, Github):
            backend.api.close()
        else:
            backend.api.session.close()
        assert not thread.is_alive()


def test_snapshot_integrity_and_reference_closure() -> None:
    """
    Reject edited snapshots, unrecorded endpoints and missing recursive components offline.

    Returns:
        None: Both committed snapshots match manifest hashes and local references resolve.
    """
    manifest = object_value(json.loads((DATA / "manifest.json").read_text()))
    for provider, raw in manifest.items():
        entry = object_value(raw)
        content = (DATA / f"{provider}.json").read_bytes()
        assert hashlib.sha256(content).hexdigest() == entry["snapshot_sha256"]
        document = object_value(json.loads(content))
        assert object_value(document["responses"]).keys() == object_value(entry["endpoints"]).keys()
        for reference in references(document):
            resolved(document, {"$ref": reference})


def test_refresh_preserves_recursive_components_and_rejects_missing_operations() -> None:
    """
    Prove slicing preserves cycles without inventing absent GET contracts.

    Returns:
        None: Recursive references survive and unsupported endpoint selection fails visibly.
    """
    component = {"type": "object", "properties": {"child": {"$ref": "#/components/schemas/node"}}}
    document: dict[str, object] = {
        "openapi": "3.0.0",
        "info": {},
        "paths": {"/nodes": {"get": {"responses": {"200": component}}}},
        "components": {"schemas": {"node": component}},
    }
    original = copy.deepcopy(document)
    selected = select(document, {"nodes": "/nodes"})
    assert selected["components"] == document["components"]
    assert document == original
    assert select(document, {"nodes": "/nodes"}) == selected
    with pytest.raises(KeyError):
        select(document, {"missing": "/missing"})


def test_schema_rejects_invalid_response_types() -> None:
    """
    Ensure invalid fixture values fail before the mock server can normalize them.

    Returns:
        None: A string masquerading as a GitLab boolean is rejected.
    """
    with pytest.raises(AssertionError, match="boolean"):
        response_body("gitlab", "diffs", [{"diff": "", "collapsed": "false"}])


def test_refresh_binds_bytes_without_mutating_input(monkeypatch: MonkeyPatch) -> None:
    """
    Preserve source/snapshot hashes across defensive mapping copies and reject changed source bytes.

    Args:
        monkeypatch (MonkeyPatch): Supply a bounded in-memory public specification response.

    Returns:
        None: Output pins are complete, inputs unchanged, and same-pin byte drift fails closed.
    """
    document = {"openapi": "3.0.0", "info": {}, "paths": {"/nodes": {"get": {"responses": {"200": {"description": "OK"}}}}}}
    source = encoded(document)
    manifest: dict[str, object] = {
        "github": {
            "revision": "a" * 40,
            "url": "https://raw.githubusercontent.com/github/rest-api-description/{revision}/spec.json",
            "endpoints": {"nodes": "/nodes"},
        },
    }
    original = copy.deepcopy(manifest)
    monkeypatch.setattr("provider_contracts.refresh.urlopen", lambda url, timeout: BytesIO(source))
    updated, snapshots = refresh(manifest, {})
    entry = object_value(updated["github"])
    assert entry["source_sha256"] == hashlib.sha256(source).hexdigest()
    assert entry["snapshot_sha256"] == hashlib.sha256(snapshots["github"]).hexdigest()
    assert manifest == original
    assert refresh(updated, {}) == (updated, snapshots)
    monkeypatch.setattr("provider_contracts.refresh.urlopen", lambda url, timeout: BytesIO(source + b"\n"))
    with pytest.raises(ValueError, match="source bytes changed"):
        refresh(updated, {})
    with pytest.raises(ValueError, match="immutable"):
        refresh(manifest, {"github": "main"})


def test_example_redaction_preserves_schema_constraints() -> None:
    """
    Keep fixture normalization out of required values and validation expressions.

    Returns:
        None: Only example emails change; patterns and caller-owned values remain intact.
    """
    address = "sample" + "@" + "vendor.example"
    source = {"pattern": address, "example": address, "examples": {"response": {"value": {"email": address}}}}
    result = object_value(redact_examples(source))
    assert result["pattern"] == address
    assert result["example"] == "fixture@example.invalid"
    assert result["examples"] == {"response": {"value": {"email": "fixture@example.invalid"}}}
    assert source["example"] == address


def test_latest_lookup_failure_cannot_reuse_old_snapshots(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Fail the release refresh without writing outputs when current upstream state is unavailable.

    Args:
        tmp_path (Path): Isolated snapshot destination.
        monkeypatch (MonkeyPatch): Replace only current-head lookup with an outage.

    Returns:
        None: Failure propagates, the old manifest remains intact, and no success snapshot appears.
    """
    from provider_contracts.refresh import main

    original = (DATA / "manifest.json").read_bytes()
    (tmp_path / "manifest.json").write_bytes(original)

    def unavailable() -> dict[str, str]:
        """
        Simulate an unavailable upstream without accepting the previous revision.

        Returns:
            dict[str, str]: Never returned during the simulated outage.
        """
        raise ConnectionError("Synthetic upstream lookup failure")

    monkeypatch.setattr("provider_contracts.refresh.DATA", tmp_path)
    monkeypatch.setattr("provider_contracts.refresh.latest_revisions", unavailable)
    monkeypatch.setattr("sys.argv", ["refresh.py", "--latest"])
    with pytest.raises(ConnectionError, match="lookup failure"):
        main()
    assert (tmp_path / "manifest.json").read_bytes() == original
    assert list(tmp_path.iterdir()) == [tmp_path / "manifest.json"]


@pytest.mark.parametrize("stale", [False, True])
def test_latest_check_requires_reviewed_committed_inputs(tmp_path: Path, monkeypatch: MonkeyPatch, stale: bool) -> None:
    """
    Reject a changed current specification without writing the reviewed baseline or refreshing away the failure.

    Args:
        tmp_path (Path): Disposable reviewed inputs and separate observation output.
        monkeypatch (MonkeyPatch): Replace only the explicit upstream-resolution/download boundary.
        stale (bool): Whether the immutable current specification differs from the committed pin.

    Returns:
        None: Current inputs pass unchanged; stale inputs fail with bounded independently retained evidence.
    """
    from provider_contracts.refresh import main

    baseline = {"github": {"revision": "a" * 40, "latest_observed_at": "reviewed-time"}}
    (tmp_path / "manifest.json").write_bytes(encoded(baseline))
    (tmp_path / "github.json").write_bytes(b"snapshot\n")
    original = (tmp_path / "manifest.json").read_bytes()
    current = "b" * 40 if stale else "a" * 40

    def fetch(manifest: dict[str, object], overrides: dict[str, str]) -> tuple[dict[str, object], dict[str, bytes]]:
        """
        Return exactly the resolved immutable current contract without changing the caller's inputs.

        Args:
            manifest (dict[str, object]): Reviewed source retained on disk.
            overrides (dict[str, str]): Exactly one current resolution.

        Returns:
            tuple[dict[str, object], dict[str, bytes]]: Current contract and deterministic synthetic bytes.
        """
        assert overrides == {"github": current}
        return {"github": {**object_value(manifest["github"]), "revision": current}}, {"github": b"snapshot\n"}

    monkeypatch.setattr("provider_contracts.refresh.DATA", tmp_path)
    monkeypatch.setattr("provider_contracts.refresh.latest_revisions", lambda: {"github": current})
    monkeypatch.setattr("provider_contracts.refresh.refresh", fetch)
    observation = tmp_path / "evidence/latest.json"
    monkeypatch.setattr("sys.argv", ["refresh.py", "--check", "--latest", "--observation", str(observation)])
    assert main() == int(stale)
    assert (tmp_path / "manifest.json").read_bytes() == original
    assert (tmp_path / "github.json").read_bytes() == b"snapshot\n"
    assert json.loads(observation.read_text())["current"] is not stale


def test_latest_resolution_uses_sdk_query_namespace(monkeypatch: MonkeyPatch) -> None:
    """
    Exercise the locked SDK URL construction so a vendor filter cannot replace its resource endpoint.

    Args:
        monkeypatch (MonkeyPatch): Intercept only HTTP transport; both real SDK managers construct requests.

    Returns:
        None: GitLab file filtering stays in the query string and both current immutable revisions are returned.
    """
    from provider_contracts.refresh import latest_revisions

    seen: list[str] = []

    def send(self: Session, request: PreparedRequest, **kwargs: object) -> Response:
        """
        Return minimal metadata only for the expected SDK requests, refusing every other network destination.

        Args:
            self (Session): SDK-owned request session.
            request (PreparedRequest): Fully constructed SDK request.
            **kwargs (object): Requests transport options, unused by this deterministic boundary.

        Returns:
            Response: Synthetic public metadata for the exact expected path and file filter.
        """
        assert request.url is not None
        url = urlsplit(request.url)
        query = parse_qs(url.query)
        data: object
        if url.hostname == "api.github.com" and url.path == "/repos/github/rest-api-description":
            data = {"id": 1, "full_name": "github/rest-api-description"}
        elif url.hostname == "api.github.com" and url.path == "/repos/github/rest-api-description/commits":
            assert query["path"] == ["descriptions/api.github.com/api.github.com.json"]
            assert query["sha"] == ["main"]
            data = [{"sha": "a" * 40}]
        else:
            assert url.hostname == "gitlab.com"
            assert unquote(url.path) == "/api/v4/projects/gitlab-org/gitlab/repository/commits"
            assert query["path"] == ["doc/api/openapi/openapi_v3.yaml"]
            assert query["ref_name"] == ["master"]
            assert query["per_page"] == ["1"]
            data = [{"id": "b" * 40}]
        seen.append(url.path)
        response = Response()
        response.status_code = HTTPStatus.OK
        response.headers["Content-Type"] = "application/json"
        response._content = encoded(data)
        response.request = request
        response.url = request.url
        return response

    monkeypatch.setattr(Session, "send", send)
    assert latest_revisions() == {"github": "a" * 40, "gitlab": "b" * 40}
    assert len(seen) == 3
