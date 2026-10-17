"""
Resolve external CI inputs once, then invoke deterministic planning and validation passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import time
from pathlib import Path

from test_matrix.core import aggregate, plan
from test_matrix.models import Plan, Report, Settings, State, load, write
from test_matrix.render import render

ROOT = Path(".cache/ci/tests")


def scope() -> str:
    """
    Bind cache compatibility to repository, runtime, runner, policy, dependencies and controller code.

    Returns:
        str: Stable digest independent of moving source or run identifiers.
    """
    digest = hashlib.sha256()
    for value in (os.environ["GITHUB_REPOSITORY"], platform.system(), platform.machine(), platform.python_version()):
        digest.update(value.encode() + b"\0")
    for path in [
        Path("poetry.lock"),
        Path(".github/test-matrix.json"),
        Path(".github/workflows/stage-tests.yml"),
        Path(".github/actions/python/action.yml"),
        *sorted(Path("scripts/ci/test_matrix").glob("*.py")),
    ]:
        digest.update(path.as_posix().encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def identify() -> None:
    """
    Expose the compatible feedback scope before cache restoration.

    Returns:
        None: One GitHub output contains the hash of authoritative inputs.
    """
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"scope={scope()}\n")


def prepare() -> None:
    """
    Emit a frozen test plan and a GitHub matrix from compatible cached feedback.

    Returns:
        None: Empty or duplicate collection fails; cache misses are explicit cold starts.
    """
    nodes = json.loads((ROOT / "nodes.json").read_bytes())
    if not isinstance(nodes, list) or not all(isinstance(node, str) for node in nodes):
        raise ValueError("Invalid pytest collection")
    key = scope()
    state = load(ROOT / "state.json", State) if (ROOT / "state.json").exists() else State(key)
    if state.scope != key:
        state = State(key)
    selected = plan(
        nodes,
        state,
        load(Path(".github/test-matrix.json"), Settings),
        os.environ["GITHUB_REPOSITORY"],
        os.environ["GITHUB_SHA"],
        f"{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}",
        float(os.environ["TEST_MATRIX_STARTED_AT"]),
    )
    write(ROOT / "plan.json", selected)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write("matrix=" + json.dumps({"shard": list(range(len(selected.partitions)))}) + "\n")
        output.write(f"workers={selected.settings.workers}\nscope={key}\n")


def finish() -> None:
    """
    Validate this run's exact fan-in and prepare feedback, aggregates and its documentation plot.

    Returns:
        None: Immutable plan bindings prevent partial, duplicate or mismatched acceptance.
    """
    selected = load(ROOT / "plan.json", Plan)
    if (selected.repository, selected.source, selected.run) != (
        os.environ["GITHUB_REPOSITORY"],
        os.environ["GITHUB_SHA"],
        f"{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}",
    ):
        raise ValueError("Test plan belongs to another source or run")
    reports = []
    for path in sorted((ROOT / "shards").glob("*/report.json")):
        report = load(path, Report)
        coverage = path.parent / f".coverage.{report.shard}"
        if not coverage.is_file() or coverage.stat().st_size == 0:
            raise ValueError("Every shard must supply its raw coverage")
        reports.append(report)
    state, sample = aggregate(
        selected, hashlib.sha256((ROOT / "plan.json").read_bytes()).hexdigest(), reports, time.time() - selected.started_at
    )
    write(ROOT / "state.json", state)
    write(ROOT / "sample.json", sample)
    destination = ROOT / "publication"
    measurement = destination / ".github/metrics/tests" / f"{selected.run}.json"
    write(measurement, sample)
    # A cache is expendable. Durable public history comes from reviewed per-run aggregate records.
    history = [*Path(".github/metrics/tests").glob("*.json"), measurement]
    render(history, destination / "docs/assets/test-convergence.svg", selected.repository, selected.scope)
    files = {
        path.relative_to(destination).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(destination.rglob("*"))
        if path.is_file()
    }
    write(
        ROOT / "publication.json",
        {"source": selected.source, "run": selected.run, "repository": selected.repository, "scope": selected.scope, "files": files},
    )


def capture_enabled() -> None:
    """
    Prevent generated-only main updates from creating an endless measurement publication loop.

    Returns:
        None: A GitHub output flag permits accepted state writes only for source-bearing main pushes.
    """
    enabled = os.environ["GITHUB_EVENT_NAME"] == "push" and os.environ["GITHUB_REF"] == "refs/heads/main"
    if enabled:
        paths = subprocess.run(
            ["git", "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "HEAD"], check=True, text=True, capture_output=True
        ).stdout.splitlines()
        prefixes = (".github/metrics/tests/", "docs/assets/test-convergence.svg", "scripts/ci/provider_contracts/data/")
        enabled = any(not path.startswith(prefixes) for path in paths)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"enabled={str(enabled).lower()}\n")


def main() -> None:
    """
    Dispatch cohesive planning, fan-in and publication-eligibility stages.

    Returns:
        None: The selected operation completes or propagates a validation failure.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(required=True)
    commands.add_parser("scope").set_defaults(handler=identify)
    commands.add_parser("plan").set_defaults(handler=prepare)
    commands.add_parser("finish").set_defaults(handler=finish)
    commands.add_parser("capture").set_defaults(handler=capture_enabled)
    args = parser.parse_args()
    args.handler()


if __name__ == "__main__":
    main()
