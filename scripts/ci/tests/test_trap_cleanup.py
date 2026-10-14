"""
Verify production EXIT handlers preserve failures and remove only their owned synthetic files.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from textwrap import dedent

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_HANDLERS = (
    (".github/workflows/ci.yml", "cleanup_raw_directory", ("raw findings/report.json",)),
    (
        "scripts/ci/publish-views.sh",
        "cleanup_view_payload",
        ("view payload", "view payload.rows", "view payload.response", "view payload.encoded"),
    ),
    ("scripts/release/setup-signing.sh", "cleanup_plaintext_key", ("signing backup/openssl.key",)),
)


@pytest.mark.parametrize(("source_path", "handler", "owned"), _HANDLERS)
@pytest.mark.parametrize(("command_status", "cleanup_fails", "expected_status"), ((0, False, 0), (7, False, 7), (0, True, 1), (7, True, 7)))
def test_exit_cleanup_contract(
    tmp_path: Path, source_path: str, handler: str, owned: tuple[str, ...], command_status: int, cleanup_fails: bool, expected_status: int
) -> None:
    """
    Exercise actual handler definitions without running scans, generating keys, or contacting services.

    Args:
        tmp_path (Path): Isolated synthetic working directory.
        source_path (str): Maintained workflow or script containing the handler.
        handler (str): Named EXIT handler extracted for execution.
        owned (tuple[str, ...]): Relative files that this handler owns.
        command_status (int): Exit status produced by the simulated command.
        cleanup_fails (bool): Whether removal fails with a distinct status.
        expected_status (int): Final process status required by the handler contract.

    Returns:
        None: Exit status, cleanup scope, diagnostics, and single invocation are asserted.
    """
    # Extract the maintained definition and registration; never copy its implementation into the test.
    source = (_ROOT / source_path).read_text()
    definition = re.search(rf"^(?P<indent> *){re.escape(handler)}\(\) \{{\n.*?^(?P=indent)\}}$", source, re.MULTILINE | re.DOTALL)
    registration = re.search(rf"^ *trap {re.escape(handler)} EXIT$", source, re.MULTILINE)
    assert definition is not None and registration is not None
    script = tmp_path / "handler.sh"
    script.write_text(dedent(definition.group()) + "\n" + registration.group().strip() + "\n")

    # Unrelated files and retained signing backups must survive every handler and failure path.
    original = {name for _, _, paths in _HANDLERS for name in paths} | {"signing backup/cosign.key", "unrelated.txt"}
    for name in original:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic fixture")

    result = subprocess.run(
        ["bash", str(_ROOT / "scripts/ci/tests/fixtures/trap-cleanup.sh"), str(script)],
        env={
            **os.environ,
            "TEST_DIRECTORY": str(tmp_path),
            "TEST_COMMAND_STATUS": str(command_status),
            "TEST_CLEANUP_FAIL": str(cleanup_fails).lower(),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_status, result.stderr
    assert (tmp_path / "cleanup.calls").read_text().splitlines() == ["cleanup"]
    expected_remaining = original if cleanup_fails else original - set(owned)
    assert {name for name in original if (tmp_path / name).exists()} == expected_remaining
    assert ("Failed to remove" in result.stderr) is cleanup_fails
