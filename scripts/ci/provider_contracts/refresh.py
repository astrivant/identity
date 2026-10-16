"""
Refresh a bounded set of vendor OpenAPI operations at explicitly reviewed revisions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.request import urlopen

import yaml
from github import Auth, Github
from github.GithubRetry import GithubRetry
from gitlab import Gitlab
from witful.delivery.providers.base import object_value, string

if TYPE_CHECKING:
    from urllib3.response import BaseHTTPResponse

DATA = Path(__file__).with_name("data")

MAX_SERVER_WAIT = 120.0
MAX_JITTER = 1.0


class BoundedGithubRetry(GithubRetry):
    """
    Keep SDK rate-limit classification while bounding every wait, including Retry-After.
    """

    def sleep(self, response: BaseHTTPResponse | None = None) -> None:
        """
        Wait at least the server delay plus jitter, or fail without retrying early.

        Args:
            response (BaseHTTPResponse | None): Failed response, absent for transport errors.

        Returns:
            None: The selected bounded delay has elapsed.

        Raises:
            TimeoutError: The server requires more than the per-retry wait budget.
        """
        # The SDK handles reset timestamps and secondary limits; urllib3 parses Retry-After seconds or dates.
        retry_after = self.get_retry_after(response) if response is not None else None
        delay = retry_after if retry_after is not None else self.get_backoff_time()
        if delay > MAX_SERVER_WAIT:
            raise TimeoutError("GitHub retry requires more than the 120-second wait budget; rerun after the rate limit resets")

        # Jitter must follow the server's minimum, never shorten it or let concurrent runners retry together.
        time.sleep(max(0.0, delay) + random.uniform(0.0, MAX_JITTER))


def github_retry() -> BoundedGithubRetry:
    """
    Limit read-only metadata requests to three attempts and at most 242 seconds of retry sleep.

    Returns:
        BoundedGithubRetry: SDK retry policy with finite transport/status attempts and header-aware waits.
    """
    return BoundedGithubRetry(
        total=2,
        other=0,
        allowed_methods=frozenset({"GET"}),
        backoff_factor=1.0,
        max_rate_limit_wait=MAX_SERVER_WAIT,
    )


def encoded(value: object) -> bytes:
    """
    Serialize snapshots deterministically for review and digest comparison.

    Args:
        value (object): JSON-compatible snapshot.

    Returns:
        bytes: Indented, sorted JSON with a final newline.
    """
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def references(value: object) -> set[str]:
    """
    Find references without interpreting arbitrary strings as schema paths.

    Args:
        value (object): Selected operation or referenced component.

    Returns:
        set[str]: Literal OpenAPI references, including recursive dependencies.
    """
    if isinstance(value, dict):
        return {string(item) for key, item in value.items() if key == "$ref"} | set().union(*(references(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(references(item) for item in value))
    return set()


def redact_examples(value: object, in_example: bool = False) -> object:
    """
    Replace sample email addresses only within vendor examples, preserving constraints.

    Args:
        value (object): Selected JSON tree.
        in_example (bool): Whether this subtree belongs to an example payload.

    Returns:
        object: New tree with reserved sample addresses and unchanged schema semantics.
    """
    if isinstance(value, dict):
        return {key: redact_examples(item, in_example or key in {"example", "examples"}) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_examples(item, in_example) for item in value]
    if isinstance(value, str) and in_example:
        # Preserve SSH user syntax while using reserved domains for all sample addresses.
        return re.sub(
            r"\b[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[A-Z0-9-]+\.)+[A-Z]{2,}\b",
            lambda match: "git@example.invalid" if match.group().lower().startswith("git@") else "fixture@example.invalid",
            value,
            flags=re.IGNORECASE,
        )
    return value


def select(document: dict[str, object], endpoints: dict[str, object]) -> dict[str, object]:
    """
    Retain GET success contracts and their exact local component closure.

    Args:
        document (dict[str, object]): Vendor-owned OpenAPI source.
        endpoints (dict[str, object]): Named endpoint paths consumed by delivery tests.

    Returns:
        dict[str, object]: Unmodified selected response definitions and referenced components.

    Raises:
        ValueError: The source changes dialect or introduces nonlocal component references.
    """
    if not string(document["openapi"]).startswith("3.0."):
        raise ValueError("Review validator compatibility before adopting another OpenAPI dialect")
    paths = object_value(document["paths"])
    responses = {}
    for name, path in endpoints.items():
        operation = object_value(object_value(paths[string(path)])["get"])
        responses[name] = object_value(operation["responses"])["200"]

    # Preserve references, including cycles, instead of expanding recursive schemas.
    components: dict[str, dict[str, object]] = {}
    pending, seen = references(responses), set()
    while pending:
        reference = pending.pop()
        if reference in seen:
            continue
        parts = reference.split("/")
        if len(parts) != 4 or parts[:2] != ["#", "components"]:
            raise ValueError(f"Unsupported reference: {reference}")
        group, name = parts[2:]
        component = object_value(object_value(document["components"])[group])[name]
        components.setdefault(group, {})[name] = component
        seen.add(reference)
        pending.update(references(component) - seen)
    return {"openapi": document["openapi"], "info": document["info"], "responses": responses, "components": components}


def refresh(manifest: dict[str, object], overrides: dict[str, str]) -> tuple[dict[str, object], dict[str, bytes]]:
    """
    Fetch only public specifications and bind their bytes to explicit immutable pins.

    Args:
        manifest (dict[str, object]): Reviewed source templates, pins, digests and endpoint selections.
        overrides (dict[str, str]): Explicit new commits selected for review.

    Returns:
        tuple[dict[str, object], dict[str, bytes]]: Updated manifest and generated snapshots; inputs are unchanged.

    Raises:
        ValueError: A pin is mutable, a source changes under its pin, or its URL is unsupported.
    """
    updated = object_value(json.loads(json.dumps(manifest)))
    snapshots: dict[str, bytes] = {}
    for provider, raw in updated.items():
        entry = object_value(raw)
        revision = overrides.get(provider, string(entry["revision"]))
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("Specification revisions must be full immutable commit IDs")
        url = string(entry["url"]).format(revision=revision)
        if not url.startswith(
            ("https://raw.githubusercontent.com/github/rest-api-description/", "https://gitlab.com/gitlab-org/gitlab/-/raw/")
        ):
            raise ValueError("Only the reviewed public vendor specification sources are supported")
        with urlopen(url, timeout=60) as response:
            source = response.read(32 * 1024 * 1024 + 1)
        if len(source) > 32 * 1024 * 1024:
            raise ValueError("Specification exceeds the reviewed download budget")
        digest = hashlib.sha256(source).hexdigest()
        if revision == entry["revision"] and entry.get("source_sha256") not in (None, digest):
            raise ValueError(f"{provider}: source bytes changed at the pinned revision")
        snapshot = encoded(redact_examples(select(object_value(yaml.safe_load(source)), object_value(entry["endpoints"]))))
        entry.update(revision=revision, source_sha256=digest, snapshot_sha256=hashlib.sha256(snapshot).hexdigest())
        snapshots[provider] = snapshot
        updated[provider] = entry
    return updated, snapshots


def latest_revisions() -> dict[str, str]:
    """
    Resolve the latest file-changing commit on each official specification branch through the locked SDKs.

    Returns:
        dict[str, str]: Immutable source commits observed during this invocation.
    """
    # Shared runner IPs can exhaust anonymous quota; scope an explicit token to the GitHub SDK only.
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    with Github(auth=Auth.Token(token) if token else None, retry=github_retry(), timeout=30, per_page=1, lazy=True) as github:
        github_revision = (
            github.get_repo("github/rest-api-description")
            .get_commits(sha="main", path="descriptions/api.github.com/api.github.com.json")[0]
            .sha
        )
    with Gitlab("https://gitlab.com", timeout=30) as gitlab:
        project = gitlab.projects.get("gitlab-org/gitlab", lazy=True)
        # `path` is also an SDK endpoint override; keep the vendor filter in its explicit query namespace.
        commits = project.commits.list(
            query_parameters={"ref_name": "master", "path": "doc/api/openapi/openapi_v3.yaml"}, per_page=1, get_all=False
        )
        if not commits:
            raise ValueError("No current GitLab specification revision was returned")
        gitlab_revision = string(commits[0].attributes["id"])
    return {"github": github_revision, "gitlab": gitlab_revision}


def main() -> int:
    """
    Regenerate reviewed snapshots or check their reproducibility without writing files.

    Returns:
        int: Zero when generation succeeds; one when check mode detects stale outputs.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--latest", action="store_true", help="Resolve current official spec heads, then refresh at those immutable commits"
    )
    parser.add_argument("--check", action="store_true", help="Fetch pinned sources and reject generated drift without writing")
    parser.add_argument("--observation", type=Path, help="Write per-run freshness evidence separately from reusable snapshots")
    parser.add_argument("--github-ref", help="Reviewed 40-character specification commit")
    parser.add_argument("--gitlab-ref", help="Reviewed 40-character specification commit")
    args = parser.parse_args()
    manifest_path = DATA / "manifest.json"
    manifest = object_value(json.loads(manifest_path.read_text()))
    overrides = {name: ref for name, ref in (("github", args.github_ref), ("gitlab", args.gitlab_ref)) if ref is not None}
    if (args.check and overrides) or (args.latest and overrides):
        parser.error("Explicit revision overrides cannot be combined with --check or --latest")
    if args.latest:
        overrides = latest_revisions()
    updated, snapshots = refresh(manifest, overrides)
    if not args.check:
        # Observation time belongs to the run artifact, keeping renewed bytes stable across retries.
        for name in overrides:
            entry = object_value(updated[name])
            entry.pop("latest_observed_at", None)
            updated[name] = entry
    outputs = {DATA / f"{name}.json": content for name, content in snapshots.items()}
    outputs[manifest_path] = encoded(updated)
    stale = [str(path.relative_to(DATA)) for path, content in outputs.items() if not path.exists() or path.read_bytes() != content]
    if args.observation is not None:
        args.observation.parent.mkdir(parents=True, exist_ok=True)
        args.observation.write_bytes(
            encoded(
                {
                    "observed_at": datetime.now(UTC).isoformat(),
                    "latest": args.latest,
                    "revisions": overrides,
                    "current": not stale if args.check else True,
                    "changed": stale,
                    "manifest_sha256": hashlib.sha256(manifest_path.read_bytes() if args.check else outputs[manifest_path]).hexdigest(),
                }
            )
        )
    if args.check:
        if stale:
            print("Stale API contracts: " + ", ".join(stale))
            print("Run refresh.py --latest and test the refreshed contracts.")
        return int(bool(stale))
    for path, content in outputs.items():
        path.write_bytes(content)
    print("Refreshed API contracts; review the diff, rerun contract tests, and commit the pins with their snapshots.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
