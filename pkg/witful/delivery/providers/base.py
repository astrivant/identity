"""
Define provider-neutral repository bindings and read-only delivery metadata contracts.
"""

from __future__ import annotations

from itertools import islice
from typing import TYPE_CHECKING, Protocol, TypeVar

from attrs import frozen

if TYPE_CHECKING:
    from collections.abc import Iterable

T = TypeVar("T")


@frozen
class Repository:
    """
    Bind API identity and Git transport without retaining credentials.

    Attributes:
        provider (str): GitHub or GitLab backend name.
        host (str): Explicit HTTPS API host authority.
        project (str): Namespaced repository path, including GitLab subgroups.
        remote (str): Selected local Git remote.
        url (str): Reviewed credential-free fetch/push URL.
    """

    provider: str
    host: str
    project: str
    remote: str = "origin"
    url: str = ""

    @property
    def key(self) -> str:
        """
        Identify a project independently of local remote aliases.

        Returns:
            str: Provider, host and project qualified key.
        """
        return f"{self.provider}:{self.host}/{self.project}"

    def data(self) -> dict[str, object]:
        """
        Serialize the complete publication binding into a receipt.

        Returns:
            dict[str, object]: Public transport identity without tokens.
        """
        return {"provider": self.provider, "host": self.host, "project": self.project, "remote": self.remote, "url": self.url}


def object_value(value: object) -> dict[str, object]:
    """
    Validate an API object before reading provider fields.

    Args:
        value (object): Decoded JSON value.

    Returns:
        dict[str, object]: String-keyed response object.

    Raises:
        ValueError: The response is not an object.
    """
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Expected an API object")
    return {str(key): item for key, item in value.items()}


def string(value: object) -> str:
    """
    Require a provider string without coercing malformed metadata.

    Args:
        value (object): API field.

    Returns:
        str: Validated field.
    """
    if not isinstance(value, str):
        raise ValueError("Expected an API string")
    return value


def integer(value: object) -> int:
    """
    Validate a nonnegative count or request identifier.

    Args:
        value (object): API field.

    Returns:
        int: Validated count.
    """
    if type(value) is not int or value < 0:
        raise ValueError("Expected a nonnegative integer")
    return value


class Backend(Protocol):
    """
    Supply normalized review requests and provider-specific signature evidence.
    """

    def requests(self) -> list[dict[str, object]]:
        """
        Read the complete bounded open-request inventory.

        Returns:
            list[dict[str, object]]: Common request fields with separately labelled provider evidence.
        """
        ...

    def default_branch(self) -> str:
        """
        Read the protected integration branch name.

        Returns:
            str: Provider-reported default branch.
        """
        ...

    def verified(self, revision: str) -> bool:
        """
        Check the host's signature verification for an exact immutable commit.

        Args:
            revision (str): Full commit identifier.

        Returns:
            bool: Whether this host verified that commit's signature.
        """
        ...


def bounded(values: Iterable[T]) -> list[T]:
    """
    Consume an SDK iterator within the complete-inventory limit.

    Args:
        values (Iterable[T]): SDK-managed paginated records.

    Returns:
        list[T]: Complete inventory below the cap; failures never return a partial list.
    """
    rows = list(islice(values, 1000))
    if len(rows) >= 1000:
        raise ValueError("Capped delivery inventory; narrow the project outside this helper")
    return rows
