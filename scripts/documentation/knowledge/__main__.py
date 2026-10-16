"""
Render public README examples from invented engineering activity, never a personal collection.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib as mpl
from witful.knowledge.contracts import as_data
from witful.knowledge.metrics import graph_edges
from witful.knowledge.plotting import save_figure, write_plots

from .examples import examples
from .overview import overview


def main() -> int:
    """
    Render separate collection views plus a complete synthetic ownership forest.

    Returns:
        int: Zero after deterministic SVG/PNG previews and inspectable graph inputs are written.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".cache/readme-preview"))
    args = parser.parse_args()
    collections = examples()
    args.output.mkdir(parents=True, exist_ok=True)

    with mpl.rc_context(mpl.rcParamsDefault):
        mpl.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none", "svg.hashsalt": "synthetic-collections"})

        for path in save_figure(overview(collections), args.output, "knowledge-collections"):
            print(path)

    # Each call keeps its own identity, counts and Gaussian. This presentation
    # is not a federated collection or a cross-identity retrieval operation.
    for example in collections:
        alias = example.identity.id.removeprefix("example:")

        for path in write_plots(example.identity, example.applications, args.output / alias):
            print(path)

    inputs = [
        {
            "identity": as_data(example.identity),
            "applications": [as_data(event) for event in example.applications],
            "edges": [as_data(edge) for edge in graph_edges(example.identity, example.applications)],
        }
        for example in collections
    ]
    manifest = args.output / "knowledge-collections.json"
    manifest.write_text(json.dumps({"synthetic": True, "collections": inputs}, indent=2) + "\n")
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
