"""
Reject stale view receipts and unsafe input selections using independent file changes.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence


@runtime_checkable
class Manifest(Protocol):
    """
    Describe the standalone receipt script's entrypoint.
    """

    def main(self, argv: Sequence[str] | None = None) -> int:
        """
        Write or verify the selected paths.

        Args:
            argv (Sequence[str] | None): Explicit argument vector.

        Returns:
            int: Receipt verification result.
        """
        ...


def load_script() -> Manifest:
    """
    Import the maintained helper without relying on its working directory.

    Returns:
        Manifest: The checked script interface.
    """
    script = Path(__file__).parents[1] / "view_manifest.py"
    spec = importlib.util.spec_from_file_location("view_manifest", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert isinstance(module, Manifest)
    return module


@pytest.mark.parametrize("mutation", ["source", "output", "new-source", "revision"])
def test_receipt_rejects_changed_evidence(tmp_path: Path, mutation: str) -> None:
    """
    Verify that either side of the source-to-view relationship invalidates a receipt.

    Args:
        tmp_path (Path): Isolated source and output directory.
        mutation (str): Independently changed part of the contract.

    Returns:
        None: Original bytes pass and each mutation fails.
    """
    (tmp_path / "input.jsonl").write_text("source")
    (tmp_path / "plot.svg").write_text("plot")
    args = ["--root", str(tmp_path), "--source", "*.jsonl", "--output", "*.svg", "--receipt", "receipt.json", "--revision", "a" * 40]
    module = load_script()
    assert module.main(args) == 0
    assert module.main([*args, "--check"]) == 0
    verification = ["--root", str(tmp_path), "--receipt", "receipt.json", "--revision", "a" * 40, "--verify-receipt"]
    assert module.main(verification) == 0

    if mutation == "revision":
        args[-1] = "b" * 40
    else:
        name = {"source": "input.jsonl", "output": "plot.svg", "new-source": "new.jsonl"}[mutation]
        (tmp_path / name).write_text("changed")

    assert module.main([*args, "--check"]) == 1
    if mutation in {"source", "output"}:
        assert module.main(verification) == 1


@pytest.mark.parametrize("pattern", ["missing", "../outside", "/absolute", "link"])
def test_receipt_rejects_unsafe_or_missing_files(tmp_path: Path, pattern: str) -> None:
    """
    Reject incomplete selections and references outside the owned source tree.

    Args:
        tmp_path (Path): Isolated source directory.
        pattern (str): Invalid source selector.

    Returns:
        None: Unsafe source choices fail before writing a receipt.
    """
    (tmp_path / "plot.svg").write_text("plot")
    (tmp_path / "link").symlink_to(tmp_path / "plot.svg")
    with pytest.raises(ValueError):
        load_script().main(
            ["--root", str(tmp_path), "--source", pattern, "--output", "*.svg", "--receipt", "receipt.json", "--revision", "a" * 40]
        )
    assert not (tmp_path / "receipt.json").exists()
