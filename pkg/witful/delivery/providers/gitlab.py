"""
Translate GitLab REST merge requests without treating unknown diff sizes as empty changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

from attrs import frozen

from .base import Repository, bounded, integer, object_value, string

if TYPE_CHECKING:
    from gitlab import Gitlab


@frozen
class GitLab:
    """
    Read GitLab.com or self-managed projects, including nested group paths.

    Attributes:
        repository (Repository): Explicit Git/API destination binding.
        api (Gitlab): Maintained GitLab SDK client.
    """

    repository: Repository
    api: Gitlab

    @property
    def path(self) -> str:
        """
        Encode the complete namespace as one GitLab project identifier.

        Returns:
            str: Relative project endpoint.
        """
        return "/projects/" + quote(self.repository.project, safe="")

    def default_branch(self) -> str:
        """
        Read the project's current default branch.

        Returns:
            str: Integration branch name.
        """
        return string(self.api.projects.get(self.repository.project, max_retries=0).attributes["default_branch"])

    def requests(self) -> list[dict[str, object]]:
        """
        Read MRs and exact-head commit statuses, retaining provider review and pipeline evidence.

        Returns:
            list[dict[str, object]]: Normalized requests; unavailable line counts remain null.
        """
        result: list[dict[str, object]] = []
        project = self.api.projects.get(self.repository.project, max_retries=0)
        for summary in bounded(project.mergerequests.list(state="opened", order_by="created_at", sort="asc", iterator=True, max_retries=0)):
            identifier = integer(summary.attributes["iid"])
            path = self.path + f"/merge_requests/{identifier}"
            request = project.mergerequests.get(identifier, max_retries=0)
            row = object_value(request.attributes)
            if row["state"] != "opened":
                raise ValueError("MR inventory changed during collection; retry")
            revision = string(row["sha"])
            refs = object_value(row.get("diff_refs") or {})
            # Diff preparation is asynchronous and may lag the current source revision.
            count = row.get("changes_count")
            known = isinstance(count, str) and count.isdecimal() and refs.get("head_sha") == revision
            diffs = (
                [object_value(item) for item in bounded(self.api.http_list(path + "/diffs", iterator=True, max_retries=0))] if known else []
            )
            known = (
                known
                and len(diffs) == int(str(count))
                and all(not item.get("collapsed") and not item.get("too_large") and isinstance(item.get("diff"), str) for item in diffs)
            )
            additions = deletions = 0
            for diff in diffs:
                for line in string(diff.get("diff", "")).splitlines():
                    additions += int(line.startswith("+"))
                    deletions += int(line.startswith("-"))
            result.append(
                {
                    "key": f"{self.repository.key}#{identifier}",
                    "repository": self.repository.key,
                    "provider": "gitlab",
                    "remote": self.repository.remote,
                    "number": identifier,
                    "title": string(row["title"]),
                    "url": string(row["web_url"]),
                    "body": row.get("description") or "",
                    "headRefName": string(row["source_branch"]),
                    "headRefOid": revision,
                    "baseRefName": string(row["target_branch"]),
                    "baseRefOid": refs.get("start_sha"),
                    "isCrossRepository": row.get("source_project_id") is None or row["source_project_id"] != row["target_project_id"],
                    "additions": additions if known else None,
                    "deletions": deletions if known else None,
                    "changedFiles": len(diffs) if known else None,
                    "isDraft": row.get("draft", False),
                    "reviewDecision": row.get("detailed_merge_status") or "unknown",
                    "reviews": {"reviewers": row.get("reviewers", []), "merge_status": row.get("detailed_merge_status")},
                    "statusCheckRollup": {
                        "head": revision,
                        "statuses": [
                            object_value(item.asdict())
                            for item in bounded(project.commits.get(revision, lazy=True).statuses.list(iterator=True, max_retries=0))
                        ],
                        "head_pipeline": row.get("head_pipeline"),
                    },
                }
            )
        return result

    def verified(self, revision: str) -> bool:
        """
        Require GitLab's signature result at the immutable commit endpoint.

        Args:
            revision (str): Full immutable commit identifier.

        Returns:
            bool: Whether GitLab verifies the commit; an unsigned 404 remains a verification failure.
        """
        row = object_value(
            self.api.projects.get(self.repository.project, lazy=True).commits.get(revision, lazy=True).signature(max_retries=0)
        )
        return row.get("verification_status") == "verified"
