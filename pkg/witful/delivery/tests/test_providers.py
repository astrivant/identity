"""
Exercise real SDK parsing with synthetic HTTPS responses and explicit destination contracts.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from github import Github
from gitlab import Gitlab
from requests import Response, Session
from witful.delivery import common, prs
from witful.delivery.providers import backend
from witful.delivery.providers.base import Repository
from witful.delivery.providers.github import GitHub
from witful.delivery.providers.gitlab import GitLab

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch
    from requests import PreparedRequest


@pytest.fixture
def sdk_responses(monkeypatch: MonkeyPatch) -> dict[str, object]:
    """
    Intercept HTTPS at requests' transport boundary while retaining both real SDKs.

    Args:
        monkeypatch (MonkeyPatch): Replace transport only; no live credentials or server calls.

    Returns:
        dict[str, object]: Mutable endpoint fixtures for success, pagination and error responses.
    """
    fixtures: dict[str, object] = {}

    def send(session: Session, request: PreparedRequest, **options: object) -> Response:
        """
        Return only declared fixture responses and preserve SDK pagination headers.

        Args:
            session (Session): SDK-owned requests session.
            request (PreparedRequest): Prepared REST request.
            **options (object): SDK transport options.

        Returns:
            Response: Synthetic JSON response.
        """
        assert request.method == "GET"
        assert request.url is not None
        parsed = urlsplit(request.url or "")
        key = unquote(parsed.path)
        page = parse_qs(parsed.query).get("page", ["1"])[0]
        if page != "1":
            key += ":" + page
        assert key in fixtures, key
        value = fixtures[key]
        response = Response()
        response.status_code = 403 if value == "denied" else 200
        response.url = request.url
        response.request = request
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps({"message": "private provider detail"} if value == "denied" else value).encode()
        if key + ":2" in fixtures:
            response.headers["Link"] = f'<https://{parsed.hostname}{parsed.path}?page=2&per_page=100>; rel="next"'
            response.headers["X-Next-Page"] = "2"
        return response

    monkeypatch.setattr(Session, "send", send)
    return fixtures


def github_rows(fixtures: dict[str, object], host: str = "https://api.github.com") -> GitHub:
    """
    Configure a complete PR including a second page and exact-head checks.

    Args:
        fixtures (dict[str, object]): Synthetic transport table.
        host (str): Explicit SDK endpoint; loopback for HTTP contract tests.

    Returns:
        GitHub: Actual SDK-backed provider with synthetic endpoints.
    """
    path, sha = "/repos/example/project", "a" * 40
    fixtures[path] = {"id": 1, "url": host + path, "full_name": "example/project", "default_branch": "main"}
    pull = {
        "number": 5,
        "state": "open",
        "url": host + path + "/pulls/5",
        "title": "Fixture",
        "html_url": "https://github.com/example/project/pull/5",
        "head": {"sha": sha, "ref": "feature", "repo": {"id": 1}},
        "base": {"sha": "b" * 40, "ref": "main", "repo": {"id": 1}},
        "additions": 2,
        "deletions": 1,
        "changed_files": 1,
        "draft": False,
        "body": "Review intent",
    }
    fixtures[path + "/pulls"] = [pull]
    fixtures[path + "/pulls:2"] = []
    fixtures[path + "/pulls/5"] = pull
    fixtures[path + "/pulls/5/reviews"] = [{"id": 3, "state": "CHANGES_REQUESTED", "commit_id": sha}]
    fixtures[path + "/commits/" + sha] = {
        "sha": sha,
        "url": host + path + "/commits/" + sha,
        "commit": {"verification": {"verified": True}},
    }
    fixtures[path + "/statuses/" + sha] = [{"id": 9, "state": "pending", "context": "build"}]
    fixtures[path + "/commits/" + sha + "/check-runs"] = {"total_count": 0, "check_runs": []}
    return GitHub(Repository("github", "github.com", "example/project"), Github(base_url=host, retry=0, timeout=5))


def gitlab_rows(fixtures: dict[str, object], changes: str = "1", host: str = "https://gitlab.com") -> GitLab:
    """
    Configure a nested-group MR with an unrelated merge-result pipeline.

    Args:
        fixtures (dict[str, object]): Synthetic transport table.
        changes (str): Reported changed-file count, possibly capped or pending.
        host (str): Explicit SDK endpoint; loopback for HTTP contract tests.

    Returns:
        GitLab: Actual SDK-backed provider with synthetic endpoints.
    """
    path, sha = "/api/v4/projects/group/subgroup/project", "a" * 40
    fixtures[path] = {"id": 42, "default_branch": "main"}
    # SDK objects use the numeric project ID after resolving the nested namespace.
    project = "/api/v4/projects/42"
    row = {
        "iid": 5,
        "project_id": 42,
        "state": "opened",
        "title": "Fixture",
        "web_url": "https://gitlab.com/group/subgroup/project/-/merge_requests/5",
        "source_branch": "feature",
        "target_branch": "main",
        "sha": sha,
        "source_project_id": 42,
        "target_project_id": 42,
        "description": "Review intent",
        "diff_refs": {"head_sha": sha, "start_sha": "b" * 40},
        "changes_count": changes,
        "head_pipeline": {"sha": "c" * 40, "status": "success"},
        "detailed_merge_status": "not_approved",
    }
    fixtures[project + "/merge_requests"] = [row]
    fixtures[project + "/merge_requests/5"] = row
    fixtures[path + "/merge_requests/5/diffs"] = [
        {"diff": "@@ -1 +1,2 @@\n-old\n+new\n+++literal\n", "collapsed": False, "too_large": False}
    ]
    fixtures[project + "/repository/commits/" + sha + "/statuses"] = [{"id": 1, "sha": sha, "status": "failed", "name": "build"}]
    fixtures[path + "/repository/commits/" + sha + "/signature"] = {"verification_status": "verified"}
    return GitLab(Repository("gitlab", "gitlab.com", "group/subgroup/project", "mirror"), Gitlab(host, timeout=5))


def test_sdk_backends_retain_distinct_evidence_and_order(sdk_responses: dict[str, object]) -> None:
    """
    Combine same-number PRs and MRs without conflating review policy or pipeline revisions.

    Args:
        sdk_responses (dict[str, object]): Synthetic HTTPS table.

    Returns:
        None: Both SDKs parse pagination, namespaces, sizes, provenance and verification.
    """
    github, gitlab = github_rows(sdk_responses), gitlab_rows(sdk_responses)
    assert github.default_branch() == gitlab.default_branch() == "main"
    rows = github.requests() + gitlab.requests()
    assert len(prs.ordered(rows, {})) == 2
    assert rows[0]["key"] != rows[1]["key"]
    assert rows[1]["additions"] == 2 and rows[1]["deletions"] == 1
    assert github.verified("a" * 40) and gitlab.verified("a" * 40)
    assert rows[1]["statusCheckRollup"] == {
        "head": "a" * 40,
        "statuses": [{"id": 1, "sha": "a" * 40, "status": "failed", "name": "build"}],
        "head_pipeline": {"sha": "c" * 40, "status": "success"},
    }
    with pytest.raises(ValueError, match="ambiguous"):
        prs.ordered(rows, {"5": [5]})
    assert prs.ordered(rows, {str(rows[0]["key"]): [rows[1]["key"]]}) == [rows[1], rows[0]]
    with pytest.raises(ValueError, match="cycle"):
        prs.ordered(rows, {str(rows[0]["key"]): [rows[1]["key"]], str(rows[1]["key"]): [rows[0]["key"]]})


@pytest.mark.parametrize("changes", ["", "1000+"])
def test_pending_or_capped_gitlab_diffs_stay_unknown(sdk_responses: dict[str, object], changes: str) -> None:
    """
    Keep incomplete GitLab measurements visible instead of ranking them as zero-sized work.

    Args:
        sdk_responses (dict[str, object]): Synthetic API responses.
        changes (str): Provider's incomplete count.

    Returns:
        None: Unknown-size work sorts after measured independent requests.
    """
    github, gitlab = github_rows(sdk_responses), gitlab_rows(sdk_responses, changes)
    unknown = gitlab.requests()[0]
    known = github.requests()[0]
    assert unknown["additions"] is None and unknown["changedFiles"] is None
    assert prs.ordered([unknown, known], {}) == [known, unknown]


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_provider_denial_is_redacted(sdk_responses: dict[str, object], monkeypatch: MonkeyPatch, provider: str) -> None:
    """
    Fail closed without exposing an SDK's response body or substituting another host.

    Args:
        sdk_responses (dict[str, object]): Synthetic denied endpoint.
        monkeypatch (MonkeyPatch): Avoid consulting real credential stores.
        provider (str): Selected backend.

    Returns:
        None: Both SDK failure classes become actionable redacted errors.
    """
    import witful.delivery.providers as providers

    repository = Repository(provider, provider + ".com", "example/project")
    monkeypatch.setattr(providers, "credential", lambda repository: "")
    sdk_responses["/repos/example/project" if provider == "github" else "/api/v4/projects/example/project"] = "denied"
    with pytest.raises(ValueError, match="details withheld"):
        with backend(repository) as selected:
            selected.default_branch()


@pytest.mark.parametrize(
    "url,selector,provider,host,project",
    [
        ("git@github.com:example/project.git", "origin", "github", "github.com", "example/project"),
        ("https://gitlab.com/group/sub/project.git", "mirror", "gitlab", "gitlab.com", "group/sub/project"),
        ("ssh://git@forge.example.invalid/group/sub/project.git", "gitlab:mirror", "gitlab", "forge.example.invalid", "group/sub/project"),
        ("https://code.example.invalid/example/project", "github:origin", "github", "code.example.invalid", "example/project"),
    ],
)
def test_remote_binding_supports_both_hosts(
    tmp_path: Path, monkeypatch: MonkeyPatch, url: str, selector: str, provider: str, host: str, project: str
) -> None:
    """
    Resolve hosted and explicitly qualified self-managed repositories without credentials.

    Args:
        tmp_path (Path): Existing checkout placeholder.
        monkeypatch (MonkeyPatch): Supply matching literal remote URLs.
        url (str): Reviewed URL.
        selector (str): Explicit selection.
        provider (str): Expected backend.
        host (str): Expected host.
        project (str): Expected namespace path.

    Returns:
        None: Receipts retain exact host and transport binding and reject later changes.
    """
    monkeypatch.setattr(common, "git", lambda root, *args: url)
    value = common.destination(tmp_path, selector)
    assert (value.provider, value.host, value.project) == (provider, host, project)
    assert common.saved_destination(tmp_path, value.data()) == value
    monkeypatch.setattr(common, "git", lambda root, *args: url.replace("project", "changed"))
    with pytest.raises(ValueError, match="changed"):
        common.saved_destination(tmp_path, value.data())


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@forge.example.invalid/group/project",
        "https://gitlab.com/group/project?token=secret",
        "https://gitlab.com/group/../project",
        "https://unknown.invalid/group/project",
        "git@github.com:group/project.git\nother",
    ],
)
def test_unsafe_or_implicit_unknown_hosts_are_rejected(tmp_path: Path, monkeypatch: MonkeyPatch, url: str) -> None:
    """
    Reject ambiguous or credential-bearing destinations before any provider access.

    Args:
        tmp_path (Path): Existing directory.
        monkeypatch (MonkeyPatch): Inject a remote configuration.
        url (str): Unsupported transport URL.

    Returns:
        None: Binding fails closed.
    """
    monkeypatch.setattr(common, "git", lambda root, *args: url)
    with pytest.raises(ValueError):
        common.destination(tmp_path)


def test_known_host_rejects_mismatched_provider(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Prevent a provider override from sending the wrong platform credential to a known hosted domain.

    Args:
        tmp_path (Path): Existing directory.
        monkeypatch (MonkeyPatch): Supply one reviewed GitLab remote.

    Returns:
        None: Validation fails before SDK authentication is selected.
    """
    monkeypatch.setattr(common, "git", lambda root, *args: "https://gitlab.com/group/project")
    with pytest.raises(ValueError, match="does not match"):
        common.destination(tmp_path, "github:origin")
