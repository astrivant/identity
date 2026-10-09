"""
Verify name classification, request budgets, cache freshness, and rate-limit behavior offline.
"""

from __future__ import annotations

import io
import json
from email.message import Message
from typing import TYPE_CHECKING
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest
from sapience.registry.names import API, Response, check_names, cooldown, main, normalize, request_status

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import CaptureFixture, MonkeyPatch


@pytest.mark.parametrize("name", ["", "../oops", "https://pypi.org", "_name", "name-", "resum\u00e9", "a\n", "a" * 201])
def test_invalid_names_do_not_issue_requests(tmp_path: Path, name: str) -> None:
    """
    Reject a complete invalid batch before making even its first request.

    Args:
        tmp_path (Path): Isolated cache root.
        name (str): Malformed candidate after an otherwise valid candidate.

    Returns:
        None: No network requests occur and no partial cache appears.
    """
    with patch("sapience.registry.names.request_status", side_effect=AssertionError("Unexpected network")) as fetch:
        with pytest.raises(ValueError):
            check_names(["valid", name], tmp_path, now=100, fetch=fetch)

    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "status,state",
    [
        (200, "registered"),
        (404, "not-registered"),
        (401, "unknown"),
        (403, "unknown"),
        (429, "unknown"),
        (500, "unknown"),
        (503, "unknown"),
        (0, "unknown"),
    ],
)
def test_statuses_are_not_confused_with_availability(tmp_path: Path, status: int, state: str) -> None:
    """
    Classify only positive existence evidence and an explicit registry 404.

    Args:
        tmp_path (Path): Isolated cache root.
        status (int): HTTP or transport disposition.
        state (str): Expected observation category.

    Returns:
        None: Error responses never become candidate names or permanent cached successes.
    """
    with patch("sapience.registry.names.request_status", return_value=Response(status)) as fetch:
        result = check_names(["example"], tmp_path, now=100, fetch=fetch)[0]

    assert result.state == state
    assert result.retry_at == (160 if state == "unknown" else 0)
    assert (tmp_path / "pypi-json-v1/example.json").stat().st_mode & 0o777 == 0o600


def test_normalization_and_ttl_reduce_requests(tmp_path: Path) -> None:
    """
    Deduplicate spelling variants and only refresh expired observations.

    Args:
        tmp_path (Path): Shared cache for consecutive runs.

    Returns:
        None: Three equivalent inputs make one request; cache hits preserve observation time.
    """
    with patch("sapience.registry.names.request_status", return_value=Response(404)) as fetch:
        first = check_names(["Some_Name", "some.name", "some---name"], tmp_path, now=100, fetch=fetch)
        assert len(first) == 1 and normalize("Some_Name") == "some-name"
        second = check_names(["Some_Name"], tmp_path, now=110, ttl=20, fetch=fetch)
        assert second[0].cached and second[0].checked_at == 100
        assert fetch.call_count == 1
        third = check_names(["some-name"], tmp_path, now=120, ttl=20, fetch=fetch)
        assert not third[0].cached and third[0].checked_at == 120
        assert fetch.call_count == 2
        check_names(["some-name"], tmp_path, now=121, refresh=True, fetch=fetch)
        assert fetch.call_count == 3


def test_offline_never_uses_expired_data_as_current_evidence(tmp_path: Path) -> None:
    """
    Expired observations must not imply current availability without a fresh request.

    Args:
        tmp_path (Path): Initially empty cache root.

    Returns:
        None: Missing and expired entries are unknown offline; live hits retain their provenance.
    """
    with patch("sapience.registry.names.request_status", return_value=Response(200)) as fetch:
        assert check_names(["example"], tmp_path, now=100, offline=True, fetch=fetch)[0].state == "unknown"
        check_names(["example"], tmp_path, now=100, fetch=fetch)
        assert check_names(["example"], tmp_path, now=101, offline=True, fetch=fetch)[0].state == "registered"
        assert check_names(["example"], tmp_path, now=200, ttl=1, offline=True, fetch=fetch)[0].state == "unknown"
        assert fetch.call_count == 1


def test_429_stops_batch_and_forced_refresh_until_retry_after(tmp_path: Path) -> None:
    """
    Respect the registry-wide limit across names, invocations, and refresh requests.

    Args:
        tmp_path (Path): Persistent cache stand-in.

    Returns:
        None: No requests occur during the cooldown; queries resume at its documented boundary.
    """
    with patch("sapience.registry.names.request_status", return_value=Response(429, "180")) as fetch:
        first = check_names(["one", "two", "three"], tmp_path, now=100, fetch=fetch)
        assert fetch.call_count == 1
        assert all(result.state == "unknown" and result.retry_at == 280 for result in first)
        assert not first[0].cached and first[1].cached
        check_names(["four"], tmp_path, now=200, refresh=True, fetch=fetch)
        assert fetch.call_count == 1
        check_names(["four"], tmp_path, now=280, fetch=fetch)
        assert fetch.call_count == 2


@pytest.mark.parametrize(
    "header,expected",
    [(None, 160), ("oops", 160), ("0", 160), ("-1", 160), ("Thu, 01 Jan 1970 00:05:00 GMT", 300), ("Thu, 01 Jan 1970 00:00:00 GMT", 160)],
)
def test_retry_after_formats(header: str | None, expected: int) -> None:
    """
    Accept either HTTP header form without retry storms on invalid data.

    Args:
        header (str | None): Retry-After value supplied by a response.
        expected (int): Earliest permitted next Unix timestamp.

    Returns:
        None: Invalid headers retain the minimum cooldown.
    """
    assert cooldown(header, 100) == expected


@pytest.mark.parametrize("fault", ["corrupt", "future", "mismatched", "wrong-type"])
def test_invalid_cache_is_disposable(tmp_path: Path, fault: str) -> None:
    """
    Refresh malformed cache without trusting it as availability evidence.

    Args:
        tmp_path (Path): Isolated cache.
        fault (str): Synthetic corruption category.

    Returns:
        None: Damaged local state is replaced by the latest valid registry response.
    """
    with patch("sapience.registry.names.request_status", return_value=Response(404)) as fetch:
        check_names(["example"], tmp_path, now=100, fetch=fetch)
        path = tmp_path / "pypi-json-v1/example.json"
        data = json.loads(path.read_text())

        if fault == "corrupt":
            path.write_text("{")
        else:
            field, value = {"future": ("checked_at", 300), "mismatched": ("name", "other"), "wrong-type": ("http_status", "404")}[fault]
            data[field] = value
            path.write_text(json.dumps(data))

        check_names(["example"], tmp_path, now=200, fetch=fetch)
        assert fetch.call_count == 2


def test_network_errors_remain_unknown_and_do_not_leak_details() -> None:
    """
    Transport failures and unexpected response destinations never imply a name is missing.

    Returns:
        None: Failure details stay out of observations and no response body is read.
    """
    with patch("sapience.registry.names.urlopen", side_effect=URLError("synthetic private proxy detail")):
        assert request_status("example", 5) == Response(0)

    error = HTTPError(API.format(name="example"), 404, "Not Found", Message(), None)

    with patch("sapience.registry.names.urlopen", side_effect=error):
        assert request_status("example", 5) == Response(404)

    with patch("sapience.registry.names.urlopen") as fetch:
        response = fetch.return_value.__enter__.return_value
        response.url, response.status = "https://elsewhere.invalid", 200
        response.headers.get.return_value = None
        assert request_status("example", 5) == Response(0)
        response.read.assert_not_called()


def test_cli_batches_stdin_and_reports_unknown(tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]) -> None:
    """
    Keep machine output compact and signal incomplete evidence via the process status.

    Args:
        tmp_path (Path): Empty local cache.
        monkeypatch (MonkeyPatch): Isolated stdin replacement.
        capsys (CaptureFixture[str]): Captured stdout and stderr streams.

    Returns:
        None: Deduplicated JSONL preserves registry provenance; diagnostics stay on stderr.
    """
    monkeypatch.setattr("sys.stdin", io.StringIO("SAPIENCE\n\nsapience\n"))
    assert main(["--stdin", "--offline", "--cache-dir", str(tmp_path)]) == 2
    output = capsys.readouterr()
    rows = [json.loads(line) for line in output.out.splitlines()]
    assert len(rows) == 1 and rows[0]["name"] == "sapience" and rows[0]["registry"] == "pypi"
    assert rows[0]["state"] == "unknown" and rows[0]["checked_at"] is None
    assert "not a reservation" in output.err
