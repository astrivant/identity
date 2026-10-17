"""
Render the six reviewed native-storage views and bind editable sources, implementation, schemas and reference configuration by digest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import textwrap
from pathlib import Path

import matplotlib
import networkx as nx
from attrs import frozen
from matplotlib import pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from witful.knowledge.contracts import structure

from . import bindings

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "docs/native/diagrams"
# Echo the README logo without making color the only indication of a state class.
COLORS = {"authority": "#e2ddba", "pending": "#efd6c5", "projection": "#d6e0e9", "cache": "#f5f1e7", "service": "#eeeff0"}


@frozen
class Node:
    """
    Define one explicitly positioned state or service boundary.

    Attributes:
        id (str): View-local stable node identifier.
        label (str): Reviewed multiline state/ownership label.
        kind (str): State class selecting the shared legend color.
        x (float): Horizontal diagram coordinate.
        y (float): Vertical diagram coordinate.
    """

    id: str
    label: str
    kind: str
    x: float
    y: float


@frozen
class Edge:
    """
    Define one named directional contract between existing boundaries.

    Attributes:
        source (str): Existing source node.
        target (str): Existing destination node.
        label (str): Transport, ordering or verification condition.
        bend (float): Explicit curvature for a reviewed non-linear link.
    """

    source: str
    target: str
    label: str
    bend: float = 0.0


@frozen
class View:
    """
    Retain an editable as-built explanation with direct implementation references.

    Attributes:
        id (str): Stable output filename stem.
        title (str): Concise view title.
        question (str): Evidence question directly under the title.
        nodes (tuple[Node, ...]): Explicit state and responsibility inventory.
        edges (tuple[Edge, ...]): Named contracts connecting that inventory.
        notes (str): Operational qualifications printed below the diagram.
        sources (tuple[str, ...]): Repository-relative implemented contracts.
    """

    id: str
    title: str
    question: str
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    notes: str
    sources: tuple[str, ...]


@frozen
class Package:
    """
    Define the closed editable diagram package.

    Attributes:
        views (tuple[View, ...]): Exactly the six required storage views.
    """

    views: tuple[View, ...]


def digest(path: Path) -> str:
    """
    Hash an exact source or rendered artifact without depending on filesystem metadata.

    Args:
        path (Path): Existing local regular file.

    Returns:
        str: SHA-256 of the exact current bytes.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs(package: Package) -> dict[str, str]:
    """
    Bind the native implementation, SQL schema, locked dependencies and actual reviewed reference configurations.

    Args:
        package (Package): Reviewed view references.

    Returns:
        dict[str, str]: Stable repository-relative digest inventory; missing referenced contracts fail explicitly.
    """
    paths = {path for pattern in ("pkg/witful/native/**/*.py", "pkg/witful/sql/postgres/native/**/*.sql") for path in ROOT.glob(pattern)}
    paths.update(ROOT / source for view in package.views for source in view.sources)
    paths.update(
        (DIRECTORY / "views.json", Path(__file__), Path(bindings.__file__), ROOT / "poetry.lock", ROOT / "helm/witful/values.schema.json")
    )
    return {str(path.relative_to(ROOT)): digest(path) for path in sorted(paths)}


def separate_coordinates(svg: str) -> str:
    """
    Use SVG comma separators for generated path coordinates while preserving labels, numeric values and path commands.

    Args:
        svg (str): Trusted Matplotlib SVG output, with path data in double-quoted attributes.

    Returns:
        str: Equivalent path geometry without ambiguous phone-shaped numeric whitespace; all other text remains byte-identical.
    """
    return re.sub(
        r'(<path d=")([^"]*)(")',
        lambda match: match[1] + re.sub(r"(?<=[0-9.])\s+(?=[-+.0-9])", ",", match[2]) + match[3],
        svg,
    )


def render(view: View, preview: Path | None) -> None:
    """
    Render readable SVG text and an optional local PNG from the same reviewed coordinates and labels.

    Args:
        view (View): One typed and graph-validated view.
        preview (Path | None): Optional local visual-review directory, not another authoritative source.

    Returns:
        None: One SVG and optionally one PNG are written; input objects remain unchanged.
    """
    graph: nx.DiGraph[str, dict[str, object], dict[str, object]] = nx.DiGraph()
    graph.add_nodes_from(node.id for node in view.nodes)
    assert len(graph) == len(view.nodes), "Duplicate diagram node"
    for edge in view.edges:
        assert edge.source in graph and edge.target in graph, "Unexplained diagram link"
        graph.add_edge(edge.source, edge.target)
    positions = {node.id: (node.x, node.y) for node in view.nodes}
    figure, axes = plt.subplots(figsize=(16, 11))
    figure.subplots_adjust(left=0.035, right=0.965, bottom=0.19, top=0.86)
    minimum = min(node.y for node in view.nodes)
    axes.set(xlim=(-0.66, 4.6 if any(edge.bend for edge in view.edges) else 3.66), ylim=(minimum - 0.5, 2.5))
    axes.axis("off")
    boxes: dict[str, FancyBboxPatch] = {}
    for node in view.nodes:
        box = FancyBboxPatch(
            (node.x - 0.60, node.y - 0.23),
            1.20,
            0.46,
            boxstyle="round,pad=0.025",
            facecolor=COLORS[node.kind],
            edgecolor="#65737b",
            linewidth=1.0,
            zorder=2,
        )
        axes.add_patch(box)
        boxes[node.id] = box
        axes.text(node.x, node.y, node.label, ha="center", va="center", fontsize=10.5, linespacing=1.45, zorder=3)
    for edge in view.edges:
        start, end = positions[edge.source], positions[edge.target]
        axes.add_patch(
            FancyArrowPatch(
                start,
                end,
                patchA=boxes[edge.source],
                patchB=boxes[edge.target],
                arrowstyle="-|>",
                mutation_scale=13,
                color="#65737b",
                linewidth=1.0,
                connectionstyle=f"arc3,rad={edge.bend}",
                zorder=1,
            )
        )
        axes.text(
            (start[0] + end[0]) / 2 + edge.bend * 0.65,
            (start[1] + end[1]) / 2 + 0.05,
            textwrap.fill(edge.label, 23),
            ha="center",
            va="center",
            fontsize=8.8,
            color="#263642",
            zorder=4,
            bbox={"facecolor": "#fffdf8", "edgecolor": "none", "pad": 1.5},
        )
    figure.text(0.5, 0.956, view.title, ha="center", va="top", fontsize=20, weight="bold")
    figure.text(0.5, 0.919, view.question, ha="center", va="top", fontsize=13, color="#263642")
    figure.text(0.04, 0.12, textwrap.fill(view.notes, 165), ha="left", va="top", fontsize=9.5, linespacing=1.5)
    figure.text(
        0.04,
        0.032,
        "OLIVE authoritative  |  COPPER durable pending  |  BLUE replicated projection  |  CREAM disposable cache  |  GRAY service",
        fontsize=9,
        color="#263642",
    )
    figure.savefig(DIRECTORY / (view.id + ".svg"), metadata={"Date": None, "Creator": "Witful native storage diagram renderer"})
    output = DIRECTORY / (view.id + ".svg")
    output.write_text(separate_coordinates(output.read_text()))
    if preview is not None:
        preview.mkdir(parents=True, exist_ok=True)
        figure.savefig(preview / (view.id + ".png"), dpi=130)
    plt.close(figure)


def main() -> int:
    """
    Generate reviewed views or check that their source/configuration and rendered bytes still match the retained binding.

    Returns:
        int: Zero for a complete current package; failed assertions identify stale or missing acceptance evidence.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--date", help="Explicit verification date; update when reviewing changed contracts")
    args = parser.parse_args()
    package = structure(json.loads((DIRECTORY / "views.json").read_text()), Package)
    assert {view.id for view in package.views} == {"state-trust", "write-ack", "branches-review", "projection", "recovery", "migration"}
    manifest = json.loads((DIRECTORY / "manifest.json").read_text())
    assert manifest["schema"] == 2 and manifest["bindings"] == "bindings", "Unsupported diagram binding layout"
    directory = DIRECTORY / "bindings"
    current = inputs(package)
    outputs = {view.id + ".svg": DIRECTORY / (view.id + ".svg") for view in package.views}
    if args.check:
        bindings.check(directory / "inputs", current)
        bindings.check(directory / "outputs", {name: digest(path) for name, path in outputs.items()})
        return 0
    assert args.date, "Supply --date after reviewing the current contracts"
    matplotlib.use("Agg")
    with plt.rc_context(
        {
            "font.family": "DejaVu Sans",
            "text.color": "#263642",
            "figure.facecolor": "#fffdf8",
            "svg.fonttype": "none",
            "svg.hashsalt": "witful-native-storage-v1",
        }
    ):
        for view in package.views:
            render(view, args.preview)
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    # Independent source changes must not rewrite one shared commit/date field or unchanged evidence.
    for kind, hashes in (("inputs", current), ("outputs", {name: digest(path) for name, path in outputs.items()})):
        retained = bindings.read(directory / kind)
        bindings.write(directory / kind, bindings.reconcile(hashes, retained, revision, args.date))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
