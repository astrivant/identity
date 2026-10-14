"""
Translate GitHub REST pull requests into the shared delivery review contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from attrs import frozen

from .base import Repository, bounded, object_value, string

if TYPE_CHECKING:
    from github import Github


@frozen
class GitHub:
    """
    Read GitHub.com or Enterprise Server pull requests and commit verification.

    Attributes:
        repository (Repository): Explicit Git/API destination binding.
        api (Github): Maintained GitHub SDK client.
    """

    repository: Repository
    api: Github

    def default_branch(self) -> str:
        """
        Read the repository's current default branch.

        Returns:
            str: Integration branch name.
        """
        return self.api.get_repo(self.repository.project).default_branch

    def requests(self) -> list[dict[str, object]]:
        """
        Read open PRs, exact-head check evidence and raw reviews without inferring merge approval.

        Returns:
            list[dict[str, object]]: Normalized requests with provider-labelled review evidence.
        """
        result: list[dict[str, object]] = []
        project = self.api.get_repo(self.repository.project)
        for pull in bounded(project.get_pulls(state="open", sort="created", direction="asc")):
            identifier = pull.number
            pull.update()
            row = object_value(pull.raw_data)
            if row["state"] != "open":
                raise ValueError("PR inventory changed during collection; retry")
            head, base = object_value(row["head"]), object_value(row["base"])
            revision = string(head["sha"])
            commit = project.get_commit(revision)
            result.append(
                {
                    "key": f"{self.repository.key}#{identifier}",
                    "repository": self.repository.key,
                    "provider": "github",
                    "remote": self.repository.remote,
                    "number": identifier,
                    "title": string(row["title"]),
                    "url": string(row["html_url"]),
                    "body": row.get("body") or "",
                    "headRefName": string(head["ref"]),
                    "headRefOid": revision,
                    "baseRefName": string(base["ref"]),
                    "baseRefOid": string(base["sha"]),
                    "isCrossRepository": head.get("repo") is None or object_value(head["repo"])["id"] != object_value(base["repo"])["id"],
                    "additions": pull.additions,
                    "deletions": pull.deletions,
                    "changedFiles": pull.changed_files,
                    "isDraft": row.get("draft", False),
                    "reviewDecision": "inspect provider evidence",
                    "reviews": [object_value(item.raw_data) for item in bounded(pull.get_reviews())],
                    "statusCheckRollup": {
                        "head": revision,
                        "statuses": [object_value(item.raw_data) for item in bounded(commit.get_statuses())],
                        "check_runs": [object_value(item.raw_data) for item in bounded(commit.get_check_runs())],
                    },
                }
            )
        return result

    def verified(self, revision: str) -> bool:
        """
        Require GitHub verification bound to the exact requested commit.

        Args:
            revision (str): Full immutable commit identifier.

        Returns:
            bool: Whether GitHub verifies that commit's signature.
        """
        row = object_value(self.api.get_repo(self.repository.project).get_commit(revision).raw_data)
        return row["sha"] == revision and object_value(object_value(row["commit"])["verification"]).get("verified") is True
