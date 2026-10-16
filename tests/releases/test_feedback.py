"""
Exercise real SDK pagination and release comments plus pure release-note preservation.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from attrs import evolve
from release.feedback import END, START, Contribution, Inventory, comment, inventory, notes
from release.report import notify
from witful.delivery.providers.base import object_value

from tests.releases.conftest import BASE, PREFIX, SOURCE

if TYPE_CHECKING:
    from pathlib import Path

    from tests.releases.conftest import Host


def test_inventory_uses_merged_history_and_deduplicates_pagination(host: Host) -> None:
    """
    Use the frozen range and paginate associations without repeated contributor entries.

    Args:
        host (Host): Real SDK with schema-validated loopback fixtures.

    Returns:
        None: Repeated associations produce one contribution and all pages are requested.
    """
    endpoint = PREFIX + f"/commits/{SOURCE}/pulls"
    host.responses[endpoint + ":2"] = host.responses[endpoint]
    result = inventory(host.repository, "v1.1.0", SOURCE)
    assert result.previous_source == BASE
    assert result.previous_tag == "v1.0.0"
    assert [item.number for item in result.contributions] == [5]
    assert endpoint + ":2" in host.seen


@pytest.mark.parametrize("change", ["unmerged", "different-range", "excluded", "different-repository"])
def test_inventory_excludes_unreleased_or_review_excluded_requests(host: Host, change: str) -> None:
    """
    Avoid announcing open PRs, another release's merge or explicitly excluded changes.

    Args:
        host (Host): Local SDK service.
        change (str): Membership or review exclusion scenario.

    Returns:
        None: Only included contributions are retained.
    """
    pull = object_value(host.responses[PREFIX + "/pulls/5"])
    if change == "unmerged":
        pull["merged"] = False
    elif change == "different-range":
        pull["merge_commit_sha"] = "c" * 40
    elif change == "excluded":
        pull["labels"] = [
            {
                "name": "release:exclude",
                "color": "ffffff",
                "id": 1,
                "node_id": "label",
                "url": "https://example.invalid/label",
                "default": False,
            }
        ]
    else:
        base = object_value(pull["base"])
        base["repo"] = {**object_value(base["repo"]), "full_name": "example/elsewhere"}
        pull["base"] = base
    host.responses[PREFIX + "/pulls/5"] = pull
    assert not inventory(host.repository, "v1.1.0", SOURCE).contributions


def test_comparison_truncation_and_moved_tag_fail(host: Host) -> None:
    """
    Refuse a success claim when the release range cannot be resolved completely.

    Args:
        host (Host): Local SDK service.

    Returns:
        None: Both source drift and missing comparison rows are rejected.
    """
    with pytest.raises(ValueError, match="built source"):
        inventory(host.repository, "v1.1.0", "c" * 40)
    comparison = object_value(host.responses[PREFIX + f"/compare/{BASE}...{SOURCE}"])
    comparison["total_commits"] = 2
    host.responses[PREFIX + f"/compare/{BASE}...{SOURCE}"] = comparison
    with pytest.raises(ValueError, match="Incomplete"):
        inventory(host.repository, "v1.1.0", SOURCE)


def test_notes_preserve_unmanaged_content_and_escape_titles() -> None:
    """
    Keep maintainer prose and existing installation details unchanged on reruns.

    Returns:
        None: The managed block is idempotent and title text cannot inject mentions or markup.
    """
    value = Inventory(
        "example/project",
        "v1.1.0",
        SOURCE,
        "v1.0.0",
        BASE,
        (Contribution(5, "contributor", "Fix @everyone <script> [link](bad)", "Fixed"),),
    )
    original = "Installation and signature instructions.\n\nCustom maintainer text.\n"
    rendered = notes(value, original)
    assert rendered.endswith(original)
    assert rendered.count("## Release details") == 1
    assert "### Fixed" in rendered and "@everyone" not in rendered and "<script>" not in rendered
    assert notes(value, rendered) == rendered
    changed = evolve(value, contributions=())
    assert notes(changed, rendered).endswith(original)
    for malformed in (START, END, START + END + START + END, END + START):
        with pytest.raises(ValueError, match="markers"):
            notes(value, malformed)


@pytest.mark.parametrize("lost", [False, True])
def test_notifications_are_per_release_and_resume_uncertain_writes(host: Host, tmp_path: Path, lost: bool) -> None:
    """
    Persist comments once even when the server accepts a write before dropping its response.

    Args:
        host (Host): Local SDK server with mutable accepted comments.
        tmp_path (Path): Receipt destination.
        lost (bool): Whether the first accepted POST loses its response.

    Returns:
        None: Retries preserve earlier release comments and notify only the intended opener.
    """
    value = inventory(host.repository, "v1.1.0", SOURCE)
    url = "https://github.com/example/project/releases/tag/v1.1.0"
    host.lose_response = lost
    receipt = tmp_path / "receipt.json"
    assert notify(host.repository, value, url, receipt)
    assert notify(host.repository, value, url, receipt)
    assert len(host.posts) == 1
    assert "@contributor" in host.posts[0] and "v1.1.0" in host.posts[0]
    assert json.loads(receipt.read_text())["results"][0]["status"] == "already-notified"
    assert notify(host.repository, evolve(value, tag="v1.2.0"), url.replace("v1.1.0", "v1.2.0"), receipt)
    assert len(host.posts) == 2 and len(host.comments) == 2


def test_preview_and_denied_write_have_distinct_receipts(host: Host, tmp_path: Path) -> None:
    """
    Keep dry-run previews read-only and permanent write failures resumable.

    Args:
        host (Host): Local SDK server.
        tmp_path (Path): Disposable reporting receipts.

    Returns:
        None: Preview sends nothing and denied reporting cannot claim completion.
    """
    value = inventory(host.repository, "v1.1.0", SOURCE)
    receipt = tmp_path / "receipt.json"
    assert notify(host.repository, value, "https://example.invalid/release", receipt, dry_run=True)
    assert not host.posts
    host.deny = True
    assert not notify(host.repository, value, "https://example.invalid/release", receipt)
    assert len(host.posts) == 1 and not host.comments
    assert json.loads(receipt.read_text())["results"][0]["status"] == "unconfirmed"
    deleted = evolve(value.contributions[0], opener="")
    assert "@" not in comment(value, deleted, "https://example.invalid/release")


def test_first_release_and_backport_select_only_reachable_history(host: Host) -> None:
    """
    Handle a first release and ignore an unrelated newer stable ancestor candidate.

    Args:
        host (Host): Schema-validated SDK service.

    Returns:
        None: The fallback is full reachable history and a later backport uses a reachable baseline.
    """
    from tests.support.provider_contracts import response_body

    releases = host.responses[PREFIX + "/releases"]
    host.responses[PREFIX + "/releases"] = []
    url = host.repository.url
    host.responses[PREFIX + "/commits"] = response_body("github", "commits", [{"sha": SOURCE, "url": url + "/commits/" + SOURCE}])
    first = inventory(host.repository, "v1.1.0", SOURCE)
    assert first.previous_tag == "" and first.previous_source == ""
    assert len(first.contributions) == 1
    assert isinstance(releases, list)
    host.responses[PREFIX + "/releases"] = response_body(
        "github",
        "releases",
        [
            {"tag_name": "v1.0.9", "draft": False, "prerelease": False},
            *releases,
        ],
    )
    other = "c" * 40
    host.responses[PREFIX + "/commits/v1.0.9"] = response_body("github", "commit", {"sha": other, "files": []})
    host.responses[PREFIX + f"/compare/{other}...{SOURCE}"] = response_body("github", "comparison", {"status": "diverged"})
    assert inventory(host.repository, "v1.1.0", SOURCE).previous_tag == "v1.0.0"


def test_existing_human_marker_does_not_suppress_the_automation_comment(host: Host, tmp_path: Path) -> None:
    """
    Require bot ownership before treating a matching marker as a prior notification.

    Args:
        host (Host): Actual SDK over loopback.
        tmp_path (Path): Reporting receipt root.

    Returns:
        None: A contributor cannot suppress the notification by posting its marker.
    """
    from tests.support.provider_contracts import response_body

    value = inventory(host.repository, "v1.1.0", SOURCE)
    body = comment(value, value.contributions[0], "https://example.invalid/release")
    rows = response_body("github", "issue_comments", [{"body": body, "user": {"login": "contributor", "type": "User"}}])
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    host.comments.append(rows[0])
    assert notify(host.repository, value, "https://example.invalid/release", tmp_path / "receipt.json")
    assert len(host.posts) == 1 and len(host.comments) == 2
