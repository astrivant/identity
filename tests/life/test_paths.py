"""
Verify bounded Life paths, exact retrieval, privacy and renderer inputs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from attrs import evolve
from documentation.life_example import example
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.text import Text
from witful.life.cli import main
from witful.life.contracts import current_decisions
from witful.life.journal import renderer_fingerprint
from witful.life.models import Archive
from witful.life.path_plot import RESOURCES, figure
from witful.life.paths import lookup, select
from witful.life.replay import render
from witful.privacy.scanner import scan_svg

if TYPE_CHECKING:
    from pytest import CaptureFixture, MonkeyPatch


ROOT = Path(__file__).parents[2]


def test_selection_conserves_history_and_explicit_edges() -> None:
    """
    Account for every event while retaining current heads and explicit revision paths.

    Returns:
        None: No source mutation, invented edges, omitted heads or uncounted history occurs.
    """
    archive = example(ROOT)
    before = repr(archive)
    view = select(archive)
    assert view == select(archive)
    assert repr(archive) == before
    assert len(view.lanes) == 8
    assert view.omitted_subjects == 1
    assert view.omitted_events == 3
    assert sum(len(lane.events) for lane in view.lanes) + view.omitted_events == len(archive.events)
    heads = {event.id for event in current_decisions(archive)}
    for lane in view.lanes:
        assert lane.events[-1].id in heads
        assert all(right.decision.supersedes == left.id for left, right in zip(lane.events, lane.events[1:], strict=False))
    assert len({lane.events[0].decision.key for lane in view.lanes}) == len(view.lanes)
    assert select(Archive()).lanes == ()
    with pytest.raises(ValueError, match="positive"):
        select(archive, revisions=0)
    with pytest.raises(ValueError, match="hash chain"):
        select(evolve(archive, events=archive.events[::-1]))


def test_lookup_matches_current_state_before_filters() -> None:
    """
    Prevent retired or revised decisions being silently replaced by older matching records.

    Returns:
        None: Current heads, history, conjunctive exact filters and bounds remain distinct.
    """
    archive = example(ROOT)
    assert lookup(archive) == current_decisions(archive)
    retired = lookup(archive, key="cache", concept="audit", task="example:review")
    assert len(retired) == 1 and retired[0].decision.status == "retired"
    assert len(lookup(archive, key="cache", history=True)) == 2
    assert len(lookup(archive, key="retention", history=True, limit=2)) == 2
    assert not lookup(archive, concept="missing")
    assert not lookup(archive, task="example")
    assert lookup(archive, limit=1)[0] == archive.events[-1]
    with pytest.raises(ValueError, match="positive"):
        lookup(archive, limit=0)


def test_cli_uses_lookup_without_mutation(monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]) -> None:
    """
    Exercise the actual command parser and JSON contract with exact filters and invalid bounds.

    Args:
        monkeypatch (MonkeyPatch): Substitute storage loading with a validated synthetic archive.
        capsys (CaptureFixture[str]): Capture public command output.

    Returns:
        None: The filtered command returns only the requested history and fails invalid limits.
    """
    archive = example(ROOT)
    monkeypatch.setattr("witful.life.cli.read_archive", lambda root: archive)
    assert main(["show", "--key", "cache", "--concept", "audit", "--task", "example:review", "--history", "--limit", "1"]) == 0
    values = json.loads(capsys.readouterr().out)
    assert len(values) == 1 and values[0]["decision"]["status"] == "retired"
    with pytest.raises(SystemExit) as error:
        main(["show", "--limit", "0"])
    assert error.value.code == 2


def test_paths_render_with_bounded_labels_and_packaged_style(tmp_path: Path) -> None:
    """
    Check real text bounds, exact typography, transparent background and stable exported bytes.

    Args:
        tmp_path (Path): Isolated generated artifact destination.

    Returns:
        None: Populated and empty figures fit their canvas and repeat rendering leaves bytes unchanged.
    """
    archive = example(ROOT)
    for source in (archive, Archive()):
        plot = figure(source)
        FigureCanvasAgg(plot)
        plot.canvas.draw()
        assert plot.patch.get_alpha() == 0
        assert plot.get_figheight() <= 9.7
        for text in plot.findobj(Text):
            if not text.get_visible() or not text.get_text():
                continue
            assert text.get_fontproperties().get_file() == str(RESOURCES / "EBGaramond-Regular.otf")
            bounds = text.get_window_extent()
            assert bounds.x0 >= 0 and bounds.y0 >= 0
            assert bounds.x1 <= plot.bbox.width and bounds.y1 <= plot.bbox.height
    outputs = render(archive, ROOT, tmp_path)
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in outputs}
    render(archive, ROOT, tmp_path)
    assert before == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in outputs}
    report = json.loads((tmp_path / "life.json").read_text())
    assert len(report["events"]) == len(archive.events)
    assert report["paths"]["omitted_events"] == 3
    # Byte identity is checked within this toolchain, not against a preview rendered on another OS.
    assert 'id="EBGaramond' in (tmp_path / "life.svg").read_text()
    assert not scan_svg((tmp_path / "life.svg").read_text())
    assert (RESOURCES / "palette.json").read_bytes() == (ROOT / "docs/assets/brand/pr-palette.json").read_bytes()


def test_replay_fingerprint_includes_packaged_assets(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Reject reuse of a renderer identity after a font or palette changes independently of Python code.

    Args:
        tmp_path (Path): Isolated minimal package resource tree.
        monkeypatch (MonkeyPatch): Point the fingerprint reader at the owned test tree.

    Returns:
        None: A resource-only change alters the rendering contract fingerprint.
    """
    package = tmp_path / "package"
    resource = package / "life/resources"
    resource.mkdir(parents=True)
    for name in ("files.py", "lessons.py"):
        (package / name).write_text("# synthetic source\n")
    palette = resource / "palette.json"
    palette.write_text("{}")
    monkeypatch.setattr("witful.life.journal.__file__", str(package / "life/journal.py"))
    before = renderer_fingerprint(tmp_path)
    palette.write_text('{"foreground": "#243746"}')
    assert before != renderer_fingerprint(tmp_path)
