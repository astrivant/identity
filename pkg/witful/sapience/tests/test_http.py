"""
Reject unsafe remote endpoints before sending credentials or opening connections.
"""

from __future__ import annotations

import asyncio

import pytest
from witful.sapience.client import connect_http


@pytest.mark.parametrize(
    "url",
    [
        "http://remote.invalid/mcp",
        "ftp://remote.invalid",
        "https://user:password@remote.invalid",
        "https://remote.invalid/?key=private",
        "https:///mcp",
    ],
)
def test_invalid_http_configuration(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep bearer credentials out of insecure or ambiguous endpoint locations.

    Args:
        url (str): Rejected endpoint.
        monkeypatch (pytest.MonkeyPatch): Synthetic credential scope.

    Returns:
        None: Configuration fails without network access or credential disclosure.
    """
    monkeypatch.setenv("FIXTURE_TOKEN", "synthetic-token")

    async def run() -> None:
        """
        Enter the connection boundary with deliberately invalid inputs.

        Returns:
            None: Validation fails before a client session exists.
        """
        with pytest.raises(ValueError, match="HTTPS MCP endpoint") as error:
            async with connect_http(url, "FIXTURE_TOKEN"):
                pytest.fail("Unsafe endpoint was accepted")
        assert "synthetic-token" not in str(error.value)
        assert "password" not in str(error.value)

    asyncio.run(run())


@pytest.mark.parametrize("token", ["", "token\nInjected: value", "non-ascii-\u00e9"])
def test_invalid_token(token: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Reject missing or header-unsafe bearer values before contacting a server.

    Args:
        token (str): Invalid credential fixture.
        monkeypatch (pytest.MonkeyPatch): Environment scope.

    Returns:
        None: A safe validation error replaces any lower-level header exception.
    """
    monkeypatch.setenv("FIXTURE_TOKEN", token)

    async def run() -> None:
        """
        Exercise validation without a reachable network endpoint.

        Returns:
            None: No credential is transmitted.
        """
        with pytest.raises(ValueError, match="bearer token"):
            async with connect_http("https://remote.invalid/mcp", "FIXTURE_TOKEN"):
                pytest.fail("Invalid credential was accepted")

    asyncio.run(run())
