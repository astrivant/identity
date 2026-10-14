"""
Publish one verified generation through an atomic, optimistic GitHub API commit.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import TYPE_CHECKING

from witful.awareness.models import FIGURES as FIGURE_CATALOG
from witful.collection.managed import snapshot
from witful.collection.models import load_config
from witful.collection.process import run
from witful.privacy.scanner import scan_text

if TYPE_CHECKING:
    from pathlib import Path

QUERY = """mutation($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) { commit { oid } }
}"""


def publication_files(current: Path) -> dict[str, bytes]:
    """
    Select the complete encrypted generation plus explicitly approved dashboard outputs.

    Args:
        current (Path): Verified prepared generation.

    Returns:
        dict[str, bytes]: Complete finite publication surface, excluding old backups and plaintext.

    Raises:
        ValueError: A dashboard contains detected personal data or the candidate has unexpected files.
    """
    contents = snapshot(current)
    dashboard = current / "README.md"
    if dashboard.exists():
        contents["README.md"] = dashboard.read_bytes()
    config = load_config(current)
    if config.publish_figures:
        for name in FIGURE_CATALOG:
            relative = f"docs/collection/{name}.svg"
            if (current / relative).exists():
                contents[relative] = (current / relative).read_bytes()
    actual = {str(path.relative_to(current)) for path in current.rglob("*") if path.is_file()}
    if actual != set(contents) or any(path.is_symlink() for path in current.rglob("*")):
        raise ValueError("Candidate contains unexpected paths")
    for name, data in contents.items():
        if (name == "README.md" or name.endswith(".svg")) and scan_text(data.decode()):
            raise ValueError("Review readable publication content before disclosure")
    return contents


def publish(checkout: Path, output: Path, env: dict[str, str]) -> str:
    """
    Atomically update private main if its source has not advanced, then verify accepted Git blobs.

    Args:
        checkout (Path): Unmodified workflow source used to calculate readable figure deletions.
        output (Path): Prepared candidate with a final validation manifest.
        env (dict[str, str]): Trusted run metadata and job token, without decryption secrets.

    Returns:
        str: GitHub-verified committed revision containing exactly the prepared replacement bytes.

    Raises:
        ValueError: Manifest, bounded request, signature, or remote content verification fails.
    """
    from witful.collection.pipeline import authorize

    authorize(checkout, env)
    contents = publication_files(output / "current")
    manifest = json.loads((output / "VERIFIED").read_bytes())
    expected = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
    if manifest != {"source_commit": env["GITHUB_SHA"], "files": expected}:
        raise ValueError("Candidate changed after verification or belongs to another run")
    repository = env["GITHUB_REPOSITORY"]
    deletions = []
    if not load_config(output / "current").publish_figures:
        deletions = [f"docs/collection/{name}.svg" for name in FIGURE_CATALOG if (checkout / f"docs/collection/{name}.svg").is_file()]
    request = json.dumps(
        {
            "query": QUERY,
            "variables": {
                "input": {
                    "branch": {"repositoryNameWithOwner": repository, "branchName": "main"},
                    "expectedHeadOid": env["GITHUB_SHA"],
                    "message": {"headline": "Refresh verified encrypted collection"},
                    "fileChanges": {
                        "additions": [
                            {"path": name, "contents": base64.b64encode(data).decode()} for name, data in sorted(contents.items())
                        ],
                        "deletions": [{"path": name} for name in deletions],
                    },
                }
            },
        }
    ).encode()
    # Keep automatic API requests modest. Larger snapshots remain downloadable for one reviewed signed Git commit.
    if len(request) > 16 * 1024 * 1024:
        raise ValueError("Publication exceeds the 16 MiB API budget; use the retained candidate with signed Git publication")
    response = json.loads(run(["gh", "api", "graphql", "--input", "-"], data=request, env=env))
    if response.get("errors"):
        raise ValueError("GitHub rejected the atomic collection update; retain the candidate for review")
    revision = response["data"]["createCommitOnBranch"]["commit"]["oid"]
    if not isinstance(revision, str) or len(revision) != 40:
        raise ValueError("GitHub returned an invalid commit identity")
    verified = run(["gh", "api", f"repos/{repository}/commits/{revision}", "--jq", ".commit.verification.verified"], env=env)
    if verified.strip() != b"true":
        raise ValueError("GitHub did not verify the published collection commit")
    tree = json.loads(run(["gh", "api", f"repos/{repository}/git/trees/{revision}?recursive=1"], env=env))
    if tree.get("truncated"):
        raise ValueError("Remote verification tree was truncated")
    blobs = {entry["path"]: entry["sha"] for entry in tree["tree"] if entry["type"] == "blob"}
    for name, data in contents.items():
        git_digest = hashlib.sha1(f"blob {len(data)}\0".encode() + data, usedforsecurity=False).hexdigest()
        if blobs.get(name) != git_digest:
            raise ValueError("Published bytes differ from the verified candidate")
    if any(name in blobs for name in deletions):
        raise ValueError("Readable figure removal was not published")
    return revision
