"""
Own SDK clients behind one provider contract and redact remote error payloads at the boundary.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from github import Auth, Github, GithubException
from gitlab import Gitlab
from gitlab.exceptions import GitlabError
from requests.exceptions import RequestException

from .authentication import credential
from .github import GitHub
from .gitlab import GitLab

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .base import Backend, Repository


def unavailable() -> ValueError:
    """
    Describe SDK failures without disclosing response bodies or credential-bearing diagnostics.

    Returns:
        ValueError: Actionable provider-neutral failure.
    """
    return ValueError("Delivery provider unavailable; check host access, rate limits and signature status, then retry (details withheld)")


@contextmanager
def backend(repository: Repository) -> Iterator[Backend]:
    """
    Build and close the selected SDK using existing platform authentication.

    Args:
        repository (Repository): Validated selected destination.

    Yields:
        Backend: Provider implementation sharing metadata and verification contracts.
    """
    token = credential(repository)
    try:
        if repository.provider == "github":
            base = "https://api.github.com" if repository.host == "github.com" else "https://" + repository.host + "/api/v3"
            with Github(base_url=base, auth=Auth.Token(token) if token else None, timeout=30, per_page=100, retry=0) as github:
                yield GitHub(repository, github)
        elif repository.provider == "gitlab":
            with Gitlab("https://" + repository.host, oauth_token=token or None, timeout=30, per_page=100) as gitlab:
                yield GitLab(repository, gitlab)
        else:
            raise ValueError("Unsupported delivery provider")
    except (GithubException, GitlabError, RequestException):
        raise unavailable() from None
