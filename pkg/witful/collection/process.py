"""
Invoke bounded local tools without echoing private inputs or provider responses.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def run(arguments: list[str], *, data: bytes | None = None, cwd: Path | None = None, env: dict[str, str] | None = None) -> bytes:
    """
    Capture tool output and suppress potentially sensitive failure diagnostics.

    Args:
        arguments (list[str]): Literal tool arguments; never credential values.
        data (bytes | None): Optional stdin for secret projection or structured input.
        cwd (Path | None): Explicit working directory where needed.
        env (dict[str, str] | None): Scoped child environment; None inherits the caller.

    Returns:
        bytes: Captured stdout, never printed implicitly.

    Raises:
        ValueError: Tool execution fails or exceeds its two-minute bound.
    """
    try:
        result = subprocess.run(arguments, input=data, cwd=cwd, env=env, capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError(f"{Path(arguments[0]).name} could not complete; check installation and access") from None

    if result.returncode:
        raise ValueError(f"{Path(arguments[0]).name} failed; private diagnostics were withheld")

    return result.stdout


def private_repository(repository: str) -> None:
    """
    Recheck visibility through the authenticated GitHub API before publishing or decrypting.

    Args:
        repository (str): Explicit owner/repository already validated by configuration.

    Returns:
        None: GitHub reports the exact requested repository as private.

    Raises:
        ValueError: The repository is public, inaccessible, or the response is unexpected.
    """
    result: object = json.loads(run(["gh", "api", "--hostname", "github.com", f"repos/{repository}"]))

    if not isinstance(result, dict) or result.get("private") is not True or str(result.get("full_name", "")).lower() != repository.lower():
        raise ValueError("Private collection operations require an existing private GitHub repository")
