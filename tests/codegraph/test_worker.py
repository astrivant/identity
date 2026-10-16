"""
Verify the actual locked CodeGraph SDK inside its no-network disposable runtime.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from attrs import evolve
from witful.codegraph.snapshot import capture
from witful.codegraph.worker import extract

from tests.codegraph.support import repository

if TYPE_CHECKING:
    from pathlib import Path


def test_real_sdk(tmp_path: Path) -> None:
    """
    Exercise the pinned SDK against real source without mocking its responses.

    Args:
        tmp_path (Path): Disposable public synthetic fixture.

    Returns:
        None: The isolated upstream SDK returns qualified caller evidence.
    """
    image = os.environ.get("WITFUL_CODEGRAPH_IMAGE")
    if not image:
        pytest.skip("WITFUL_CODEGRAPH_IMAGE is required by the separate SDK compatibility CI job")
    enrollment, revision = repository(tmp_path / "source")
    enrollment = evolve(enrollment, image=image)
    result = extract(enrollment, capture(enrollment, revision))
    names = {node.id: node.name for node in result.nodes}
    assert {"leaf", "caller"} <= set(names.values())
    assert any(names[edge.source] == "caller" and names[edge.target] == "leaf" for edge in result.edges)
    assert not (tmp_path / "source/.codegraph").exists()
