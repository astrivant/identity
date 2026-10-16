"""
Prepare release notes or notify contributors after independently verifying publication.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

from github import Auth, Github, GithubException
from jsonschema import ValidationError
from requests.exceptions import RequestException
from witful.files import replace_file
from witful.knowledge.contracts import as_data

from .feedback import Inventory, comment, inventory, notes
from .verification import verify_release

if TYPE_CHECKING:
    from github.Repository import Repository


def notify(repository: Repository, value: Inventory, release_url: str, receipt: Path, *, dry_run: bool = False) -> bool:
    """
    Preserve permanent notifications and resume partial runs without repeating accepted comments.

    Args:
        repository (Repository): Authenticated SDK repository client with automatic write retries disabled.
        value (Inventory): Authenticated release inventory from the verified attachment set.
        release_url (str): Published release URL.
        receipt (Path): Local reporting receipt retained by the workflow even after failure.
        dry_run (bool): Produce previews without sending notifications.

    Returns:
        bool: Every contribution was reported or already had its version-specific comment.
    """
    outcomes: list[dict[str, str | int]] = []
    complete = True
    for contribution in value.contributions:
        body = comment(value, contribution, release_url)
        marker = body.splitlines()[0]
        outcome: dict[str, str | int] = {"pr": contribution.number, "status": "pending"}
        try:
            pull = repository.get_pull(contribution.number)
            existing = next(
                (item for item in pull.get_issue_comments() if item.user.login == "github-actions[bot]" and marker in item.body),
                None,
            )
            if existing:
                outcome.update(status="already-notified", url=existing.html_url)
            elif dry_run:
                outcome.update(status="preview", body=body)
            else:
                created = pull.create_issue_comment(body)
                outcome.update(status="notified", url=created.html_url)
        except (GithubException, RequestException, TimeoutError):
            # An uncertain POST may have succeeded. Reread now; never repeat it in this attempt.
            try:
                accepted = next(
                    (
                        item
                        for item in repository.get_pull(contribution.number).get_issue_comments()
                        if item.user.login == "github-actions[bot]" and marker in item.body
                    ),
                    None,
                )
            except (GithubException, RequestException, TimeoutError):
                accepted = None
            if accepted:
                outcome.update(status="already-notified", url=accepted.html_url)
            else:
                outcome.update(status="unconfirmed")
                complete = False
        outcomes.append(outcome)
        receipt.parent.mkdir(parents=True, exist_ok=True)
        replace_file(
            receipt,
            (
                json.dumps({"repository": value.repository, "tag": value.tag, "source": value.source, "results": outcomes}, indent=2) + "\n"
            ).encode(),
            expected=receipt.read_bytes() if receipt.exists() else None,
        )
    if not value.contributions:
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({"repository": value.repository, "tag": value.tag, "source": value.source, "results": []}) + "\n")
    return complete


def main() -> int:
    """
    Compose explicit preview/preparation and verified notification operations.

    Returns:
        int: Zero on success; two for invalid/unverified publication or incomplete reporting.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"), required=not os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--tag", default=os.environ.get("RELEASE_TAG"), required=not os.environ.get("RELEASE_TAG"))
    parser.add_argument("--source", default=os.environ.get("GITHUB_SHA"), required=not os.environ.get("GITHUB_SHA"))
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Read release metadata and write notes/inventory locally; no remote writes")
    prepare.add_argument("--output", type=Path, required=True)
    report = commands.add_parser("notify", help="Verify publication, then post missing permanent PR notifications")
    report.add_argument("--built", type=Path, required=True)
    report.add_argument("--download", type=Path, required=True)
    report.add_argument("--receipt", type=Path, required=True)
    report.add_argument("--fingerprint", required=True)
    report.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    try:
        # Explicit zero retries prevents transport-level POST retries from duplicating notifications.
        with Github(auth=Auth.Token(token) if token else None, retry=0, timeout=30, per_page=100) as api:
            repository = api.get_repo(args.repo)
            if args.command == "prepare":
                value = inventory(repository, args.tag, args.source)
                existing = Path(__file__).with_name("notes.md").read_text()
                try:
                    release = repository.get_release(args.tag)
                except GithubException as error:
                    if error.status != HTTPStatus.NOT_FOUND:
                        raise
                else:
                    if not release.draft:
                        raise ValueError("Published release notes are immutable")
                    existing = release.body or existing
                args.output.mkdir(parents=True, exist_ok=True)
                (args.output / "RELEASE.json").write_text(json.dumps(as_data(value), indent=2) + "\n")
                (args.output / "release-notes.md").write_text(notes(value, existing))
            else:
                release, value = verify_release(repository, args.tag, args.source, args.built, args.download, args.fingerprint)
                if not notify(repository, value, release.html_url, args.receipt, dry_run=args.dry_run):
                    print(
                        "Release verified; contributor reporting is incomplete. Inspect the receipt and rerun the reporting job.",
                        file=sys.stderr,
                    )
                    return 2
    except (OSError, ValueError, GithubException, RequestException, ValidationError, subprocess.SubprocessError):
        print(
            "Release reporting failed; inspect source, publication and access. No provider payload or credential was logged.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
