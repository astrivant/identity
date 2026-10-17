"""
Freeze pytest collection and retain explicit shard completion without changing ordinary test runs.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest

from test_matrix.models import Plan, Report, Result, load, write


def pytest_addoption(parser: pytest.Parser) -> None:
    """
    Register explicit plan and report locations for collection and execution phases.

    Args:
        parser (pytest.Parser): Shared pytest argument parser.

    Returns:
        None: Ordinary pytest invocation retains existing behavior.
    """
    parser.addoption("--matrix-collect", default=None)
    parser.addoption("--matrix-plan", default=None)
    parser.addoption("--matrix-shard", type=int, default=0)
    parser.addoption("--matrix-report", default=None)


def pytest_configure(config: pytest.Config) -> None:
    """
    Attach a process-owned recorder when this invocation selects a matrix plan.

    Args:
        config (pytest.Config): Parsed invocation.

    Returns:
        None: xdist's controller records reports; workers only filter their collection.
    """
    if config.getoption("--matrix-plan") and not hasattr(config, "workerinput"):
        config.pluginmanager.register(Recorder(config), "matrix-recorder")


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """
    Validate complete collection before selecting a disjoint frozen partition.

    Args:
        config (pytest.Config): Shared plan configuration, propagated to xdist workers.
        items (list[pytest.Item]): Collected tests after normal pytest filtering.

    Returns:
        None: All workers use the same selected order or fail on collection drift.
    """
    nodes = sorted(item.nodeid for item in items)
    if destination := config.getoption("--matrix-collect"):
        write(Path(destination), nodes)
    if location := config.getoption("--matrix-plan"):
        selected = load(Path(location), Plan)
        expected = sorted(node for group in selected.partitions for node in group)
        shard: int = config.getoption("--matrix-shard")
        if nodes != expected or not 0 <= shard < len(selected.partitions):
            raise pytest.UsageError("Test collection differs from frozen matrix plan")
        own = set(selected.partitions[shard])
        excluded = [item for item in items if item.nodeid not in own]
        items[:] = sorted((item for item in items if item.nodeid in own), key=lambda item: item.nodeid)
        config.hook.pytest_deselected(items=excluded)


class Recorder:
    """
    Accumulate terminal test phases in the controller process, never in shared worker files.
    """

    def __init__(self, config: pytest.Config) -> None:
        """
        Bind the recorder to this exact plan before test execution starts.

        Args:
            config (pytest.Config): Matrix arguments for this invocation.

        """
        self.config = config
        self.started = time.monotonic()
        self.results: dict[str, Result] = {}
        self.phases: dict[str, set[str]] = {}

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        """
        Sum setup, call and teardown while retaining skipped and failed outcomes.

        Args:
            report (pytest.TestReport): Worker phase result.

        Returns:
            None: Duplicate phases remain a failure, never silently counted twice.
        """
        phases = self.phases.setdefault(report.nodeid, set())
        previous = self.results.get(report.nodeid, Result(0.0, "passed"))
        failed = report.failed or previous.outcome == "failed" or report.when in phases
        outcome = "failed" if failed else "skipped" if report.skipped or previous.outcome == "skipped" else "passed"
        phases.add(report.when)
        self.results[report.nodeid] = Result(previous.seconds + report.duration, outcome)

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        """
        Write terminal evidence even for failed sessions, without accepting partial feedback.

        Args:
            session (pytest.Session): Completed test invocation.
            exitstatus (int): Pytest outcome.

        Returns:
            None: Aggregate validation decides whether results can train the controller.
        """
        for node, result in tuple(self.results.items()):
            if "teardown" not in self.phases[node]:
                self.results[node] = Result(result.seconds, "failed")
        destination = self.config.getoption("--matrix-report")
        if not destination:
            raise pytest.UsageError("Matrix execution requires an explicit report path")
        raw = Path(self.config.getoption("--matrix-plan")).read_bytes()
        report = Report(
            hashlib.sha256(raw).hexdigest(),
            self.config.getoption("--matrix-shard"),
            int(exitstatus),
            time.monotonic() - self.started,
            self.results,
        )
        write(Path(destination), report)
