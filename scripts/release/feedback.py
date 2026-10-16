"""
Resolve one released contribution inventory for notes and persistent PR notifications.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from attrs import frozen

if TYPE_CHECKING:
    from github.Repository import Repository

CATEGORIES = (
    ("release:breaking", "Breaking changes"),
    ("release:added", "Added"),
    ("release:changed", "Changed"),
    ("release:fixed", "Fixed"),
    ("release:security", "Security"),
    ("release:deprecated", "Deprecated / Removed"),
    ("release:docs", "Documentation / Maintenance"),
)
START = "<!-- witful-release-changes:start -->"
END = "<!-- witful-release-changes:end -->"


@frozen
class Contribution:
    """
    Retain reviewed public change metadata without collecting PR discussions.

    Attributes:
        number (int): Included merged PR number.
        opener (str): Account to notify, or empty for a deleted account.
        title (str): Public PR title, escaped at the Markdown boundary.
        category (str): Consumer category selected by reviewed labels.
    """

    number: int
    opener: str
    title: str
    category: str


@frozen
class Inventory:
    """
    Bind release communication to immutable source and its reviewed predecessor.

    Attributes:
        repository (str): GitHub owner/repository.
        tag (str): Stable version being released.
        source (str): Exact released commit.
        previous_tag (str): Previous reachable stable version, empty for the first release.
        previous_source (str): Previous released commit, empty for the first release.
        contributions (tuple[Contribution, ...]): Unique included merged PRs in number order.
    """

    repository: str
    tag: str
    source: str
    previous_tag: str
    previous_source: str
    contributions: tuple[Contribution, ...]


def version(tag: str) -> tuple[int, ...]:
    """
    Accept the same stable tag syntax as the artifact publisher.

    Args:
        tag (str): Proposed release tag.

    Returns:
        tuple[int, ...]: Numeric version components.

    Raises:
        ValueError: Prereleases or other tag formats are unsupported.
    """
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError("Expected a stable vMAJOR.MINOR.PATCH tag")
    return tuple(int(part) for part in tag[1:].split("."))


def resolve_commit(repository: Repository, reference: str) -> str:
    """
    Resolve a ref through the server before trusting the SDK object's cached SHA property.

    Args:
        repository (Repository): Authenticated or public repository client.
        reference (str): Tag or commit reference to resolve.

    Returns:
        str: Full immutable commit ID returned by GitHub.

    Raises:
        ValueError: The returned identifier is not a full commit ID.
    """
    commit = repository.get_commit(reference)
    # PyGithub can derive .sha from the request URL before fetching a tag's commit representation.
    commit.complete()
    if not re.fullmatch(r"[0-9a-f]{40}", commit.sha):
        raise ValueError("GitHub did not resolve a full commit ID")
    return commit.sha


def inventory(repository: Repository, tag: str, source: str) -> Inventory:
    """
    Enumerate actual released history through the SDK's paginated commit associations.

    Args:
        repository (Repository): Maintained SDK repository client.
        tag (str): New stable release tag.
        source (str): Expected tag commit from the build provenance.

    Returns:
        Inventory: Frozen range and included contribution metadata.

    Raises:
        ValueError: The tag moved or the host did not return the complete comparison.
    """
    current = version(tag)
    if resolve_commit(repository, tag) != source:
        raise ValueError("Release tag does not match the built source")

    # A backport selects its latest reachable older stable release, never a moving global latest.
    releases = [
        release
        for release in repository.get_releases()
        if not release.draft
        and not release.prerelease
        and re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", release.tag_name)
        and version(release.tag_name) < current
    ]
    previous_tag, previous_source = "", ""
    commits = []
    for release in sorted(releases, key=lambda item: version(item.tag_name), reverse=True):
        previous = resolve_commit(repository, release.tag_name)
        comparison = repository.compare(previous, source)
        if comparison.status in {"ahead", "identical"}:
            commits = list(comparison.commits)
            if len(commits) != comparison.total_commits:
                raise ValueError("Incomplete release comparison; refusing partial contributor coverage")
            previous_tag, previous_source = release.tag_name, previous
            break
    else:
        # The first release inventories all ancestors; direct commits remain visible through its source link.
        commits = list(repository.get_commits(sha=source))

    included = {commit.sha for commit in commits}
    pulls: dict[int, Contribution] = {}
    for commit in commits:
        for pull in commit.get_pulls():
            if pull.number in pulls:
                continue
            pull.update()
            if not pull.merged or pull.merge_commit_sha not in included or pull.base.repo.full_name != repository.full_name:
                continue
            labels = {label.name for label in pull.labels}
            if "release:exclude" in labels:
                continue
            category = next((name for label, name in CATEGORIES if label in labels), "Other changes")
            opener = pull.user.login if pull.user else ""
            if opener and not re.fullmatch(r"[A-Za-z0-9-]+(?:\[bot\])?", opener):
                raise ValueError("Invalid contribution account")
            pulls[pull.number] = Contribution(pull.number, opener, pull.title, category)
    return Inventory(repository.full_name, tag, source, previous_tag, previous_source, tuple(pulls[key] for key in sorted(pulls)))


def markdown_text(text: str) -> str:
    """
    Render untrusted titles as one line without links, HTML or additional mentions.

    Args:
        text (str): Public PR title.

    Returns:
        str: Escaped visible text with normalized whitespace.
    """
    plain = " ".join(text.split()).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("@", "&#64;")
    return re.sub(r"([\\`*_{}\[\]()#!|])", r"\\\1", plain)


def notes(value: Inventory, existing: str) -> str:
    """
    Replace only the automation-owned summary while preserving existing release details.

    Args:
        value (Inventory): Resolved contribution inventory.
        existing (str): Maintainer-authored body or the project's installation template.

    Returns:
        str: Classified notes plus the preserved release details.

    Raises:
        ValueError: Managed section markers are incomplete or duplicated.
    """
    lines = [START, "## What changed", ""]
    for category in (*[name for _, name in CATEGORIES], "Other changes"):
        changes = [pull for pull in value.contributions if pull.category == category]
        if changes:
            lines.extend([f"### {category}", ""])
            lines.extend(
                f"- {markdown_text(pull.title)} ([#{pull.number}](https://github.com/{value.repository}/pull/{pull.number}))"
                for pull in changes
            )
            lines.append("")
    if not value.contributions:
        lines.extend(["No included pull requests were identified for this release.", ""])
    if value.previous_source:
        lines.append(f"[Full comparison](https://github.com/{value.repository}/compare/{value.previous_source}...{value.source})")
    else:
        lines.append(f"[Initial released source](https://github.com/{value.repository}/tree/{value.source})")
    lines.append(END)
    section = "\n".join(lines)
    if START in existing or END in existing:
        if existing.count(START) != 1 or existing.count(END) != 1 or existing.index(START) > existing.index(END):
            raise ValueError("Ambiguous release-note markers")
        start, end = existing.index(START), existing.index(END) + len(END)
        return existing[:start] + section + existing[end:]
    details = existing if existing.startswith("## Release details\n") else "## Release details\n\n" + existing
    return section + "\n\n" + details


def comment(value: Inventory, pull: Contribution, release_url: str) -> str:
    """
    Render one permanent release-specific notification with an exact deduplication marker.

    Args:
        value (Inventory): Verified release inventory.
        pull (Contribution): Included merged contribution.
        release_url (str): Verified published release URL.

    Returns:
        str: Minimal mention, version link and repository/release/PR marker.
    """
    greeting = f"@{pull.opener}, your" if pull.opener else "This"
    return (
        f"<!-- witful-released:{value.repository}:{value.tag}:{pull.number} -->\n"
        f"{greeting} contribution in #{pull.number} was released in [Witful {value.tag}]({release_url}). "
        "Thank you for contributing."
    )
