"""
Check PyPI names in bounded batches without claiming that missing projects are reservable.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from witful.commands.registry import configure

from .constants import DEFAULT_TTL

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

API = "https://pypi.org/pypi/{name}/json"
NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")
MAX_NAMES = 100


@dataclass(frozen=True)
class Response:
    """
    Keep only the status needed from a registry response, never its package metadata.

    Attributes:
        status (int): HTTP status, or zero for a transport or redirect failure.
        retry_after (str | None): Untrusted Retry-After header, if supplied.
    """

    status: int
    retry_after: str | None = None


@dataclass(frozen=True)
class Result:
    """
    Describe one observation with enough provenance to judge its freshness.

    Attributes:
        name (str): Normalized PyPI project name.
        state (Literal["registered", "not-registered", "unknown"]): Observed registry disposition.
        checked_at (int): Unix timestamp of the actual registry check, or zero when never checked.
        http_status (int): Registry status, or zero when unavailable.
        retry_at (int): Earliest retry time after a transient failure.
        cached (bool): Whether this output reused an earlier observation.
    """

    name: str
    state: Literal["registered", "not-registered", "unknown"]
    checked_at: int
    http_status: int
    retry_at: int = 0
    cached: bool = False


def normalize(name: str) -> str:
    """
    Validate PyPA syntax before collapsing equivalent spelling variants.

    Args:
        name (str): Candidate name, not a URL or a requirement expression.

    Returns:
        str: Lowercase name with each run of dots, underscores, and dashes replaced by one dash.

    Raises:
        ValueError: Syntax is invalid or the script's 200-character input limit is exceeded.
    """
    if not NAME.fullmatch(name) or len(name) > 200:
        raise ValueError("Names must be 1-200 ASCII characters: letters, digits, dots, underscores, or dashes; start/end alphanumeric")

    return re.sub(r"[-_.]+", "-", name).lower()


def request_status(name: str, timeout: int) -> Response:
    """
    Inspect the official HTTPS endpoint without downloading or retaining its metadata body.

    Args:
        name (str): Already validated normalized name.
        timeout (int): Socket timeout in seconds.

    Returns:
        Response: Minimal status; transport failures do not expose proxy URLs or exception details.
    """
    url = API.format(name=name)
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "registry-name-check/1.0"})

    try:
        with urlopen(request, timeout=timeout) as response:
            return Response(response.status if response.url == url else 0, response.headers.get("Retry-After"))
    except HTTPError as error:
        with error:
            return Response(error.code if error.url == url else 0, error.headers.get("Retry-After"))
    except (URLError, TimeoutError, OSError):
        return Response(0)


def cooldown(value: str | None, now: int) -> int:
    """
    Respect both Retry-After formats and otherwise back off for one minute.

    Args:
        value (str | None): Header from the official registry response.
        now (int): Current Unix timestamp supplied by the caller.

    Returns:
        int: Earliest next attempt; even invalid or elapsed headers receive the minimum cooldown.
    """
    if value is not None:
        if value.isascii() and value.isdigit() and len(value) <= 10:
            return now + max(60, int(value))

        try:
            parsed = parsedate_to_datetime(value)

            if parsed.tzinfo is not None:
                return max(now + 60, int(parsed.timestamp()))
        except (ValueError, TypeError, OverflowError):
            pass

    return now + 60


def read_cache(path: Path, name: str, now: int) -> Result | None:
    """
    Treat malformed, future-dated, or incompatible disposable cache entries as misses.

    Args:
        path (Path): One namespaced per-project observation file.
        name (str): Expected normalized name, preventing cross-project cache reuse.
        now (int): Current Unix timestamp.

    Returns:
        Result | None: Validated observation or a miss; cached data is never executed.
    """
    try:
        if path.stat().st_size > 4096:
            return None

        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None

    if not isinstance(value, dict) or set(value) != {"version", "name", "state", "checked_at", "http_status", "retry_at"}:
        return None
    if value["version"] != 1 or value["name"] != name:
        return None
    if any(type(value[key]) is not int or value[key] < 0 for key in ("checked_at", "http_status", "retry_at")):
        return None
    if not 0 < value["checked_at"] <= now:
        return None

    status = value["http_status"]
    expected: Literal["registered", "not-registered", "unknown"] = (
        "registered" if status == 200 else "not-registered" if status == 404 else "unknown"
    )

    if value["state"] != expected:
        return None

    return Result(name, expected, value["checked_at"], status, value["retry_at"], cached=True)


def write_cache(path: Path, result: Result) -> None:
    """
    Atomically save compact observations with owner-only permissions.

    Args:
        path (Path): Disposable per-project destination.
        result (Result): Fresh observation, excluding any raw registry body.

    Returns:
        None: A complete JSON document replaces the prior observation.
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = asdict(result)
    del data["cached"]
    data["version"] = 1
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".observation-")

    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(data, stream, separators=(",", ":"))
            stream.write("\n")

        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def check_names(
    names: Sequence[str],
    cache_dir: Path,
    *,
    now: int,
    ttl: int = DEFAULT_TTL,
    timeout: int = 10,
    refresh: bool = False,
    offline: bool = False,
    fetch: Callable[[str, int], Response] = request_status,
) -> list[Result]:
    """
    Resolve a deduplicated batch with cache reuse and registry-wide rate-limit protection.

    Args:
        names (Sequence[str]): At most 100 candidate spellings; all validate before network access.
        cache_dir (Path): Local private cache root, automatically namespaced to the API contract.
        now (int): Explicit observation time for deterministic tests.
        ttl (int): Maximum successful observation age in seconds; zero forces fresh reads.
        timeout (int): Network timeout passed to the transport.
        refresh (bool): Ignore cached successes, but retain active rate-limit cooldowns.
        offline (bool): Never contact the registry; expired or missing observations become unknown.
        fetch (Callable[[str, int], Response]): Injectable network boundary returning status only.

    Returns:
        list[Result]: One result per normalized name, in first-seen order.

    Raises:
        ValueError: Batch size, name, or numeric options are invalid.
    """
    if not 1 <= len(names) <= MAX_NAMES or ttl < 0 or not 1 <= timeout <= 60 or now <= 0:
        raise ValueError("Supply 1-100 names, a nonnegative TTL, a 1-60 second timeout, and a positive timestamp")

    unique = dict.fromkeys(normalize(name) for name in names)
    root = cache_dir / "pypi-json-v1"
    gate_path = root / "_rate-limit.json"
    gate = read_cache(gate_path, "_rate-limit", now)
    results = []

    for name in unique:
        path = root / f"{name}.json"
        saved = read_cache(path, name, now)

        # Cached successful observations remain useful even during a registry cooldown.
        if saved is not None and saved.state != "unknown" and not refresh and now - saved.checked_at < ttl:
            results.append(saved)
            continue

        # A 429 gates the whole registry, including subsequent invocations and forced refreshes.
        if gate is not None and gate.http_status == 429 and gate.retry_at > now:
            results.append(replace(gate, name=name, cached=True))
            continue
        if saved is not None and saved.state == "unknown" and saved.retry_at > now:
            results.append(saved)
            continue
        if offline:
            results.append(Result(name, "unknown", 0, 0))
            continue

        response = fetch(name, timeout)
        state: Literal["registered", "not-registered", "unknown"] = (
            "registered" if response.status == 200 else "not-registered" if response.status == 404 else "unknown"
        )
        result = Result(name, state, now, response.status, cooldown(response.retry_after, now) if state == "unknown" else 0)
        write_cache(path, result)
        results.append(result)

        if response.status == 429:
            gate = replace(result, name="_rate-limit")
            write_cache(gate_path, gate)

    return results


def main(argv: Sequence[str] | None = None) -> int:
    """
    Print compact JSON lines or a candidate shortlist without registering or uploading packages.

    Args:
        argv (Sequence[str] | None): Explicit CLI arguments or the current process arguments.

    Returns:
        int: Zero for determinate checks, two when any observation is unknown or input is invalid.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    configure(parser)
    return execute(parser.parse_args(argv), parser)


def execute(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """
    Execute an already parsed domain command.

    Args:
        args (argparse.Namespace): Validated arguments from the shared hierarchy or standalone parser.
        parser (argparse.ArgumentParser): Owning parser for consistent error reporting.

    Returns:
        int: Selected operation status.
    """
    names = args.names

    if args.stdin:
        for line in sys.stdin:
            if line.strip():
                names.append(line.strip())

            if len(names) > MAX_NAMES:
                parser.error("At most 100 candidate names may be checked per invocation")

    try:
        results = check_names(
            names,
            args.cache_dir.expanduser(),
            now=int(time.time()),
            ttl=args.ttl_seconds,
            timeout=args.timeout_seconds,
            refresh=args.refresh,
            offline=args.offline,
        )
    except ValueError as error:
        parser.error(str(error))
    except OSError:
        parser.exit(2, "Registry cache could not be written; select a writable --cache-dir.\n")

    for result in results:
        if args.only_unregistered:
            if result.state == "not-registered":
                print(result.name)
        else:
            data = asdict(result)
            data["checked_at"] = datetime.fromtimestamp(result.checked_at, UTC).isoformat() if result.checked_at else None
            data["registry"] = "pypi"
            print(json.dumps(data, separators=(",", ":")))

    print("A missing PyPI project is not a reservation or a guarantee that the name can be registered.", file=sys.stderr)
    return 2 if any(result.state == "unknown" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
