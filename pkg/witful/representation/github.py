"""
Publish figure-only data through authenticated GitHub APIs and dispatch an immutable reference.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
from urllib.parse import quote

from witful.representation.models import BRANCH, BUNDLE_PATH, EVENT, MAX_BUNDLE_BYTES


def _api(repository: str, route: str, payload: dict[str, object] | None = None, *, missing: bool = False) -> dict[str, object]:
    """
    Call only GitHub.com through the authenticated gh client, withholding provider error bodies.

    Args:
        repository (str): Validated destination repository.
        route (str): Internally constructed repository API route.
        payload (dict[str, object] | None): POST body, or None for a GET.
        missing (bool): Return an empty object for an expected missing branch or file.

    Returns:
        dict[str, object]: Parsed provider object, empty for a successful no-content response.

    Raises:
        ValueError: GitHub rejects the operation or the response is malformed.
    """
    method = "PUT" if route == f"contents/{BUNDLE_PATH}" and payload else "POST"
    endpoint = f"repos/{repository}" + (f"/{route}" if route else "")
    command = ["gh", "api", "--hostname", "github.com", endpoint, "-H", "X-GitHub-Api-Version: 2026-03-10"]

    if payload is not None:
        command.extend(["--method", method, "--input", "-"])

    try:
        result = subprocess.run(command, input=json.dumps(payload) if payload else None, text=True, capture_output=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("GitHub request could not complete; authenticate gh for github.com and retry") from error

    if result.returncode:
        if missing and "HTTP 404" in result.stderr:
            return {}
        raise ValueError("GitHub rejected awareness publication; check repository Contents: write access and retry")

    value: object = json.loads(result.stdout) if result.stdout.strip() else {}

    if not isinstance(value, dict):
        raise ValueError("GitHub returned an unexpected response")

    return {str(key): item for key, item in value.items()}


def _sha(value: object) -> str:
    """
    Validate a Git object identifier received from GitHub.

    Args:
        value (object): Untrusted decoded field.

    Returns:
        str: Full hexadecimal commit or blob identifier.

    Raises:
        ValueError: The field is not a SHA-1 Git identifier.
    """
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("GitHub returned an invalid object identifier")
    return value


def push(repository: str, content: bytes) -> str:
    """
    Update the isolated data branch once, then dispatch the exact committed bundle.

    Args:
        repository (str): Existing owner/repository on GitHub.com.
        content (bytes): Locally rendered and reviewed figure bundle.

    Returns:
        str: Immutable data commit accepted by repository_dispatch, not a completed build.

    Raises:
        ValueError: Repository syntax, provider access, or a concurrent write prevents publication.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", repository) or len(content) > MAX_BUNDLE_BYTES:
        raise ValueError("Expected an owner/repository destination and a bundle no larger than 8 MiB")

    metadata = _api(repository, "")
    default = metadata.get("default_branch")

    if not isinstance(default, str) or default == BRANCH:
        raise ValueError("The awareness data branch must be separate from the repository default branch")

    head = _api(repository, f"git/ref/heads/{BRANCH}", missing=True)

    if not head:
        base = _api(repository, f"commits/{quote(default, safe='')}")
        head = _api(repository, "git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": _sha(base.get("sha"))})

    pointer = head.get("object")
    commit = _sha(pointer.get("sha") if isinstance(pointer, dict) else None)
    current = _api(repository, f"contents/{BUNDLE_PATH}?ref={commit}", missing=True)
    blob = hashlib.sha1(f"blob {len(content)}\0".encode() + content, usedforsecurity=False).hexdigest()

    # A repeated push reuses identical data. GitHub's expected blob SHA rejects conflicting concurrent replacements.
    if current.get("sha") != blob:
        payload: dict[str, object] = {
            "message": "docs: update selected awareness figures",
            "branch": BRANCH,
            "content": base64.b64encode(content).decode("ascii"),
        }

        if current:
            payload["sha"] = _sha(current.get("sha"))

        response = _api(repository, f"contents/{BUNDLE_PATH}", payload)
        committed = response.get("commit")
        commit = _sha(committed.get("sha") if isinstance(committed, dict) else None)

    # No URLs, executable paths, source journals, or credential values enter the dispatch payload.
    _api(
        repository,
        "dispatches",
        {
            "event_type": EVENT,
            "client_payload": {"version": 1, "commit": commit, "sha256": hashlib.sha256(content).hexdigest()},
        },
    )
    return commit
