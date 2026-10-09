"""
Verify bounded figure projection and idempotent authenticated dispatch without live publication.
"""

from __future__ import annotations

import base64
import hashlib
import json
from subprocess import CompletedProcess
from typing import TYPE_CHECKING

import pytest
from witful.awareness.github import _api, push
from witful.awareness.models import FIGURES
from witful.awareness.rendering import render
from witful.privacy.scanner import scan_text
from witful.project import main as initialize

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


def test_render_exports_only_selected_figures(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Exercise real renderers on a minimal collection while keeping journals out of transport.

    Args:
        tmp_path (Path): Temporary parent for a newly requested fixture collection.
        monkeypatch (MonkeyPatch): Inspect vector labels at the existing publication scan boundary.

    Returns:
        None: Repeated exports are deterministic and contain only the selected PNG projections.
    """
    root = tmp_path / "collection"
    assert initialize([str(root)]) == 0
    selected = tuple(FIGURES)
    labels: list[str] = []

    def inspect_labels(text: str) -> tuple[tuple[int, str], ...]:
        """
        Retain the real privacy check while observing exported vector labels.

        Args:
            text (str): SVG about to be validated for publication.

        Returns:
            tuple[tuple[int, str], ...]: The real scanner's detected personal-data patterns.
        """
        labels.append(text)
        return scan_text(text)

    monkeypatch.setattr("witful.awareness.rendering.scan_text", inspect_labels)
    content = render(root, selected)
    data = json.loads(content)
    assert set(data) == {"figures", "version"}
    assert tuple(item["id"] for item in data["figures"]) == selected
    for item in data["figures"]:
        png = base64.b64decode(item["png"], validate=True)
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        assert hashlib.sha256(png).hexdigest() == item["sha256"]
    assert render(root, selected) == content
    assert all('id="plot-heading"' not in text for text in labels)
    assert "Distinct task/context observations" in labels[0]
    assert "No disciplines recorded" in labels[1]
    assert "No accepted decisions recorded" in labels[2]
    assert not (root / "docs").exists()
    with pytest.raises(ValueError, match="disabled"):
        render(root, ())


def test_push_reuses_blob_and_dispatches_immutable_commit(monkeypatch: MonkeyPatch) -> None:
    """
    Model first publication and a retry after an accepted data commit.

    Args:
        monkeypatch (MonkeyPatch): Provider API stub with in-memory Git metadata.

    Returns:
        None: One data write serves repeated dispatches without leaking source context into the payload.
    """
    content = b'{"version":1,"figures":[]}'
    blob = hashlib.sha1(f"blob {len(content)}\0".encode() + content, usedforsecurity=False).hexdigest()
    stored = False
    dispatches: list[dict[str, object]] = []
    writes = 0

    def api(repository: str, route: str, payload: dict[str, object] | None = None, *, missing: bool = False) -> dict[str, object]:
        """
        Model a fixed remote without accepting arbitrary hosts or paths.

        Args:
            repository (str): Target repository.
            route (str): GitHub repository API route.
            payload (dict[str, object] | None): Mutation data.
            missing (bool): Whether absence is expected.

        Returns:
            dict[str, object]: Synthetic GitHub response.
        """
        nonlocal stored, writes
        assert repository == "example/resume"
        if route == "":
            return {"default_branch": "main"}
        if route == "git/ref/heads/witful-awareness":
            return {"object": {"sha": ("b" if stored else "a") * 40}}
        if route.startswith("contents/awareness.json?ref="):
            return {"sha": blob} if stored else {}
        if route == "contents/awareness.json":
            assert payload is not None and payload["branch"] == "witful-awareness"
            assert base64.b64decode(str(payload["content"])) == content
            stored = True
            writes += 1
            return {"commit": {"sha": "b" * 40}}
        if route == "dispatches":
            assert payload is not None
            dispatches.append(payload)
            return {}
        pytest.fail(f"Unexpected route {route}")

    monkeypatch.setattr("witful.awareness.github._api", api)
    assert push("example/resume", content) == "b" * 40
    assert push("example/resume", content) == "b" * 40
    assert writes == 1
    assert (
        dispatches
        == [
            {
                "event_type": "witful-awareness",
                "client_payload": {"version": 1, "commit": "b" * 40, "sha256": hashlib.sha256(content).hexdigest()},
            }
        ]
        * 2
    )


@pytest.mark.parametrize("repository", ["https://attacker.invalid/path", "example/resume?token=value", "../escape", "example/resume/extra"])
def test_push_rejects_untrusted_destinations(repository: str) -> None:
    """
    Keep token-bearing requests confined to a validated GitHub repository route.

    Args:
        repository (str): Malformed or external destination.

    Returns:
        None: Validation fails before invoking the authenticated client.
    """
    with pytest.raises(ValueError, match="owner/repository"):
        push(repository, b"{}")


def test_render_blocks_detected_personal_labels(tmp_path: Path) -> None:
    """
    Check visible source labels before PNG conversion makes them opaque to text scans.

    Args:
        tmp_path (Path): Isolated collection parent.

    Returns:
        None: A synthetic non-example email in a plot label prevents publication.
    """
    root = tmp_path / "collection"
    initialize([str(root)])
    path = root / "knowledge/catalog.json"
    catalog = json.loads(path.read_text())
    catalog["disciplines"] = [{"id": "d", "name": "owner" + "@" + "fixture-mail.dev", "skills": []}]
    path.write_text(json.dumps(catalog))

    with pytest.raises(ValueError, match="Personal-data pattern"):
        render(root, ("knowledge-hierarchy",))


def test_first_push_initializes_only_the_reserved_branch(monkeypatch: MonkeyPatch) -> None:
    """
    Create a missing transport ref from the existing default branch before publishing data.

    Args:
        monkeypatch (MonkeyPatch): Offline provider fixture.

    Returns:
        None: The source commit is used only as a parent and the final dispatch references the data commit.
    """
    routes: list[str] = []

    def api(repository: str, route: str, payload: dict[str, object] | None = None, *, missing: bool = False) -> dict[str, object]:
        """
        Return the minimal GitHub responses for a first publication.

        Args:
            repository (str): Destination repository.
            route (str): Fixed provider route.
            payload (dict[str, object] | None): Optional mutation body.
            missing (bool): Whether a missing response is expected.

        Returns:
            dict[str, object]: Synthetic API response.
        """
        routes.append(route)
        if route == "":
            return {"default_branch": "main"}
        if route == "commits/main":
            return {"sha": "a" * 40}
        if route == "git/refs":
            assert payload == {"ref": "refs/heads/witful-awareness", "sha": "a" * 40}
            return {"object": {"sha": "a" * 40}}
        if route == "contents/awareness.json":
            assert payload is not None and payload["branch"] == "witful-awareness"
            return {"commit": {"sha": "b" * 40}}
        assert missing or route == "dispatches"
        return {}

    monkeypatch.setattr("witful.awareness.github._api", api)
    assert push("example/resume", b"{}") == "b" * 40
    assert routes[-1] == "dispatches"
    assert routes.index("git/refs") < routes.index("contents/awareness.json")


def test_repository_metadata_endpoint_has_no_trailing_slash(monkeypatch: MonkeyPatch) -> None:
    """
    Exercise the real request builder rather than replacing the API adapter itself.

    Args:
        monkeypatch (MonkeyPatch): Offline gh transport replacement.

    Returns:
        None: Metadata reads use the canonical route GitHub accepts.
    """

    def run(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        """
        Assert the metadata request path at the subprocess boundary.

        Args:
            command (list[str]): Actual GitHub CLI request.
            **kwargs (object): Transport options including captured output.

        Returns:
            CompletedProcess[str]: Successful synthetic repository metadata.
        """
        assert command[4] == "repos/example/resume"
        assert kwargs["input"] is None
        return CompletedProcess(command, 0, '{"default_branch":"main"}', "")

    monkeypatch.setattr("witful.awareness.github.subprocess.run", run)
    assert _api("example/resume", "") == {"default_branch": "main"}
