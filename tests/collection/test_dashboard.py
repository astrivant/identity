"""
Verify that every readable dashboard figure survives publication and disabled views disappear.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from witful.collection import publication
from witful.collection.dashboard import CAPTIONS, FIGURES, readme
from witful.collection.models import Config

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


@pytest.mark.parametrize("visible", [False, True])
@pytest.mark.parametrize("reviews", [False, True])
def test_dashboard_disclosure(visible: bool, reviews: bool) -> None:
    """
    Bind captions and links to the current disclosure and review configuration.

    Args:
        visible (bool): Explicit readable-figure permission.
        reviews (bool): Whether optional decision-review views are enabled.

    Returns:
        None: Links are complete, deterministic, and absent when encrypted-only output is selected.
    """
    config = Config("example/collection", "a" * 64, "b" * 64, publish_figures=visible)
    text = readme(config, "c" * 64, reflection_enabled=reviews)
    linked = set(re.findall(r"docs/collection/([a-z-]+)\.svg", text))
    expected = set(FIGURES) if visible else set()
    if not reviews:
        expected -= {"decision-outcomes", "decision-context"}
    assert linked == expected
    assert set(CAPTIONS) == set(FIGURES)
    assert text == readme(config, "c" * 64, reflection_enabled=reviews)
    assert "https://github.com/example/collection/actions" in text
    assert "# Credits" in text


def test_publication_accepts_complete_dashboard(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Pass the same complete readable family through the publication boundary as through rendering.

    Args:
        tmp_path (Path): Synthetic verified candidate.
        monkeypatch (MonkeyPatch): Substitute only the already-tested encrypted snapshot loading boundary.

    Returns:
        None: Life and review figures publish; unrelated files still fail closed.
    """
    config = Config("example/collection", "a" * 64, "b" * 64, publish_figures=True)
    monkeypatch.setattr(publication, "snapshot", lambda root: {})
    monkeypatch.setattr(publication, "load_config", lambda root: config)
    (tmp_path / "README.md").write_text(readme(config, "c" * 64))
    directory = tmp_path / "docs/collection"
    directory.mkdir(parents=True)
    for name in FIGURES:
        (directory / f"{name}.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    assert set(publication.publication_files(tmp_path)) == {"README.md", *(f"docs/collection/{name}.svg" for name in FIGURES)}
    (directory / "unreviewed.json").write_text("{}")
    with pytest.raises(ValueError, match="unexpected"):
        publication.publication_files(tmp_path)
