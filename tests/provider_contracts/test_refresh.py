"""
Verify credential routing with real SDK request construction and synthetic transport responses.
"""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
import yaml
from github import RateLimitExceededException
from provider_contracts.refresh import encoded, latest_revisions
from requests import Response, Session

if TYPE_CHECKING:
    from pytest import MonkeyPatch
    from requests import PreparedRequest


@pytest.mark.parametrize(
    ("primary", "fallback", "expected", "limited"),
    [
        (None, None, None, False),
        ("synthetic-primary", "synthetic-fallback", "synthetic-primary", False),
        (None, "synthetic-fallback", "synthetic-fallback", False),
        ("", "synthetic-fallback", "synthetic-fallback", False),
        ("synthetic-primary", None, "synthetic-primary", True),
    ],
)
def test_latest_resolution_scopes_auth_and_query_filters(
    monkeypatch: MonkeyPatch, primary: str | None, fallback: str | None, expected: str | None, limited: bool
) -> None:
    """
    Preserve SDK query construction while containing optional GitHub credentials and failing closed on quota exhaustion.

    Args:
        monkeypatch (MonkeyPatch): Replace only environment and HTTP transport; real SDKs construct requests.
        primary (str | None): Synthetic GH_TOKEN value, or absence.
        fallback (str | None): Synthetic GITHUB_TOKEN value, or absence.
        expected (str | None): Selected credential, or anonymous operation.
        limited (bool): Reject the GitHub request with the observed rate-limit response.

    Returns:
        None: Only GitHub receives the selected token; a rate-limit failure makes one attempt without fallback.
    """
    for name, value in (("GH_TOKEN", primary), ("GITHUB_TOKEN", fallback)):
        monkeypatch.delenv(name, raising=False)
        if value is not None:
            monkeypatch.setenv(name, value)
    seen: list[str] = []

    def send(self: Session, request: PreparedRequest, **kwargs: object) -> Response:
        """
        Serve only the two expected SDK metadata requests without making network calls.

        Args:
            self (Session): SDK-owned session.
            request (PreparedRequest): Fully constructed SDK request.
            **kwargs (object): Original transport options, unused by the synthetic boundary.

        Returns:
            Response: Minimal metadata or the observed rate-limit failure; no response-shape coverage is implied.
        """
        assert request.url is not None
        assert request.method == "GET"
        url = urlsplit(request.url)
        query = parse_qs(url.query)
        data: object
        status = HTTPStatus.OK
        if url.hostname == "api.github.com":
            assert url.path == "/repos/github/rest-api-description/commits"
            assert request.headers.get("Authorization") == (f"token {expected}" if expected else None)
            assert query["path"] == ["descriptions/api.github.com/api.github.com.json"]
            assert query["sha"] == ["main"]
            assert query["per_page"] == ["1"]
            data = [{"sha": "a" * 40}]
            if limited:
                status = HTTPStatus.FORBIDDEN
                data = {"message": "API rate limit exceeded"}
        else:
            assert url.hostname == "gitlab.com"
            assert not {"Authorization", "PRIVATE-TOKEN"}.intersection(request.headers)
            assert unquote(url.path) == "/api/v4/projects/gitlab-org/gitlab/repository/commits"
            assert query["path"] == ["doc/api/openapi/openapi_v3.yaml"]
            assert query["ref_name"] == ["master"]
            assert query["per_page"] == ["1"]
            data = [{"id": "b" * 40}]
        seen.append(url.path)
        response = Response()
        response.status_code = status
        response.headers["Content-Type"] = "application/json"
        if limited:
            response.headers["X-RateLimit-Remaining"] = "0"
        response._content = encoded(data)
        response.request = request
        response.url = request.url
        return response

    monkeypatch.setattr(Session, "send", send)
    if limited:
        with pytest.raises(RateLimitExceededException):
            latest_revisions()
        assert len(seen) == 1
    else:
        assert latest_revisions() == {"github": "a" * 40, "gitlab": "b" * 40}
        assert len(seen) == 2


def test_workflow_limits_token_to_read_only_freshness_step() -> None:
    """
    Keep credentials out of test services and retain their explicit CI discovery path.

    Returns:
        None: Only refresh receives the built-in token under read-only job permissions.
    """
    root = Path(__file__).resolve().parents[2]
    stage = yaml.load((root / ".github/workflows/stage-provider-contracts.yml").read_text(), Loader=yaml.BaseLoader)
    assert stage["permissions"] == {"contents": "read"}
    job = stage["jobs"]["contracts"]
    assert "env" not in stage and "env" not in job
    steps = job["steps"]
    refresh_step = next(step for step in steps if "refresh.py" in step.get("run", ""))
    assert refresh_step["env"] == {"GH_TOKEN": "${{ github.token }}"}
    for step in steps:
        if step is not refresh_step:
            assert not {"GH_TOKEN", "GITHUB_TOKEN"}.intersection(step.get("env", {}))
    tests = next(step for step in steps if step.get("run", "").startswith("pytest "))
    assert "tests/provider_contracts" in tests["run"]


@pytest.mark.parametrize("changed", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
def test_renewal_succeeds_and_does_not_churn_unchanged_pins(tmp_path: Path, monkeypatch: MonkeyPatch, changed: bool, legacy: bool) -> None:
    """
    Renew metadata drift without failure while retaining separate per-run freshness evidence.

    Args:
        tmp_path (Path): Isolated snapshot directory.
        monkeypatch (MonkeyPatch): Replace external resolution and downloads only.
        changed (bool): Advance the selected upstream revision while retaining identical schemas.
        legacy (bool): Normalize an older manifest that retained observation time alongside pins.

    Returns:
        None: Refresh succeeds, observation binds current bytes, and a second refresh is idempotent.
    """
    import hashlib
    import json

    from provider_contracts import refresh as module
    from witful.delivery.providers.base import object_value

    baseline = {"github": {"revision": "a" * 40}}
    if legacy:
        baseline["github"]["latest_observed_at"] = "earlier-observation"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(encoded(baseline))
    (tmp_path / "github.json").write_bytes(b"snapshot\n")
    revision = "b" * 40 if changed else "a" * 40

    def fetch(manifest: dict[str, object], overrides: dict[str, str]) -> tuple[dict[str, object], dict[str, bytes]]:
        """
        Return a resolved revision with unchanged selected schema bytes.

        Args:
            manifest (dict[str, object]): Existing reviewed baseline.
            overrides (dict[str, str]): Once-resolved latest pins.

        Returns:
            tuple[dict[str, object], dict[str, bytes]]: New immutable manifest and selected snapshot.
        """
        assert overrides == {"github": revision}
        return {"github": {**object_value(manifest["github"]), "revision": revision}}, {"github": b"snapshot\n"}

    monkeypatch.setattr(module, "DATA", tmp_path)
    monkeypatch.setattr(module, "latest_revisions", lambda: {"github": revision})
    monkeypatch.setattr(module, "refresh", fetch)
    observation = tmp_path / "evidence/latest.json"
    monkeypatch.setattr("sys.argv", ["refresh.py", "--latest", "--observation", str(observation)])
    assert module.main() == 0
    renewed = manifest_path.read_bytes()
    evidence = json.loads(observation.read_text())
    assert evidence["current"] is True
    assert evidence["changed"] == (["manifest.json"] if changed or legacy else [])
    assert evidence["manifest_sha256"] == hashlib.sha256(renewed).hexdigest()
    assert evidence["revisions"] == {"github": revision}
    assert (renewed != encoded(baseline)) is (changed or legacy)
    assert module.main() == 0
    assert manifest_path.read_bytes() == renewed
    assert json.loads(observation.read_text())["changed"] == []
