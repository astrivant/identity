"""
Exercise scheduling invariants and reject incomplete or contaminated measurement batches.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pytest
from attrs import evolve
from test_matrix.core import aggregate, partition, plan, update
from test_matrix.models import Report, Result, Settings, State, Timing

if TYPE_CHECKING:
    from test_matrix.models import Plan


def selected(count: int = 301) -> Plan:
    """
    Produce a source-bound cold plan with independent test identities.

    Args:
        count (int): Number of collected tests.

    Returns:
        Plan: Synthetic fixture with deterministic assignments.
    """
    return plan([f"test_{i:04}" for i in range(count)], State("scope"), Settings(), "example/project", "a" * 40, "1-1")


@pytest.mark.parametrize(("count", "shards"), [(1, 1), (300, 1), (301, 2), (959, 4), (3000, 8)])
def test_threshold_and_exact_coverage(count: int, shards: int) -> None:
    """
    Assign every collected test exactly once with stable count thresholds and bounded resource use.

    Args:
        count (int): Suite size around the threshold and budget boundaries.
        shards (int): Expected cold runner count.

    Returns:
        None: No empty, duplicated or omitted assignments occur.
    """
    result = selected(count)
    flattened = [node for group in result.partitions for node in group]
    assert len(result.partitions) == shards
    assert len(flattened) == len(set(flattened)) == count
    assert all(result.partitions)


def test_partition_is_deterministic_balanced_and_preserves_input() -> None:
    """
    Balance expensive units first, independent of discovery order, without mutating caller data.

    Returns:
        None: Costs and lexical ties yield a reproducible assignment.
    """
    nodes = ["a", "b", "c", "d"]
    costs = {"a": Timing(9), "b": Timing(8), "c": Timing(2), "d": Timing(1)}
    assert partition(nodes, costs, 2, 1) == [["a", "d"], ["b", "c"]]
    assert partition(nodes[::-1], costs, 2, 1) == partition(nodes, costs, 2, 1)
    assert nodes == ["a", "b", "c", "d"] and costs["a"] == Timing(9)


@pytest.mark.parametrize("nodes", [[], ["a", "a"]])
def test_reject_empty_or_duplicated_collection(nodes: list[str]) -> None:
    """
    Refuse vacuous or ambiguous suite plans.

    Args:
        nodes (list[str]): Invalid collected identities.

    Returns:
        None: Planning cannot claim successful zero-test verification.
    """
    with pytest.raises(ValueError):
        plan(nodes, State("scope"), Settings(), "repo", "sha", "1-1")


def test_pid_converges_and_limits_pressure() -> None:
    """
    Exercise a deterministic step response and anti-windup without claiming a hosted measurement.

    Returns:
        None: The estimate converges within the deadband while every change respects its slew bound.
    """
    previous = Timing(1)
    for _ in range(40):
        current = update(previous, 3)
        assert 0.75 * previous.estimate <= current.estimate <= 1.25 * previous.estimate
        assert abs(current.integral) <= current.estimate
        previous = current
    assert abs(previous.estimate - 3) < 0.16
    assert update(Timing(3), 3.02) == Timing(3)


@pytest.mark.parametrize("duration", [0, -1, math.nan, math.inf])
def test_nonfinite_durations_are_not_feedback(duration: float) -> None:
    """
    Reject measurements that would poison future matrix sizing.

    Args:
        duration (float): Invalid timing sample.

    Returns:
        None: No invalid estimate is produced.
    """
    with pytest.raises(ValueError):
        update(None, duration)


def test_measured_resize_is_bounded_and_small_suites_remain_single() -> None:
    """
    Use prediction feedback to resize one runner at a time while preserving the user threshold.

    Returns:
        None: Expensive tests increase useful capacity; a shrinking suite returns to one runner.
    """
    nodes = [f"test_{i}" for i in range(400)]
    state = State("scope", {node: Timing(10) for node in nodes}, 2)
    settings = Settings()
    assert len(plan(nodes, state, settings, "repo", "sha", "1-1").partitions) == 3
    assert len(plan(nodes[:100], state, settings, "repo", "sha", "1-1").partitions) == 1
    assert state.shards == 2


def reports_for(value: Plan) -> list[Report]:
    """
    Create explicit complete worker reports for fan-in validation.

    Args:
        value (Plan): Immutable test assignments.

    Returns:
        list[Report]: One terminal report per worker.
    """
    return [Report("digest", i, 0, 2.0, {node: Result(1.0, "passed") for node in group}) for i, group in enumerate(value.partitions)]


def test_aggregate_accepts_complete_reports_and_prunes_deleted_tests() -> None:
    """
    Accept complete fan-in and distinguish cold starts and skips from prediction accuracy.

    Returns:
        None: Only executed surviving tests train feedback; no cold-start zero error is invented.
    """
    value = selected()
    reports = reports_for(value)
    node = value.partitions[0][0]
    reports[0].results[node] = Result(0.01, "skipped")
    state, sample = aggregate(value, "digest", reports)
    assert sample.tests == 301 and sample.skipped == 1
    assert sample.prediction_error_seconds is None and node not in state.timings
    assert len(state.timings) == 300


@pytest.mark.parametrize("fault", ["missing", "duplicate", "digest", "exit", "nodes", "failed", "nonfinite"])
def test_aggregate_rejects_partial_or_mismatched_results(fault: str) -> None:
    """
    Reject broken producer contracts before cache or generated-publication output exists.

    Args:
        fault (str): Independently injected fan-in defect.

    Returns:
        None: Every failure remains a hard validation error.
    """
    value = selected()
    reports = reports_for(value)
    if fault == "missing":
        reports.pop()
    elif fault == "duplicate":
        reports[1] = reports[0]
    elif fault == "digest":
        reports[0] = evolve(reports[0], plan_sha256="wrong")
    elif fault == "exit":
        reports[0] = evolve(reports[0], exit_code=1)
    elif fault == "nodes":
        reports[0].results.pop(next(iter(reports[0].results)))
    elif fault == "failed":
        reports[0].results[next(iter(reports[0].results))] = Result(1, "failed")
    else:
        reports[0] = evolve(reports[0], elapsed=math.nan)
    with pytest.raises(ValueError):
        aggregate(value, "digest", reports)


def test_elapsed_objective_counts_parallel_work_once_and_accounts_for_overhead() -> None:
    """
    Prefer faster completion despite greater aggregate runner time, and avoid costly observed allocations.

    Returns:
        None: Capacity search minimizes its elapsed prediction and respects measured overhead per count.
    """
    nodes = [f"test_{i}" for i in range(400)]
    state = State("scope", {node: Timing(4) for node in nodes}, 3, {"2": Timing(5), "3": Timing(200), "4": Timing(300)})
    # Two runners complete in about 205 seconds; three require about 336 despite lower test-only work time.
    result = plan(nodes, state, Settings(maximum=4), "repo", "sha", "1-1")
    assert len(result.partitions) == 2
    assert result.predicted_seconds == 205
    assert result.predicted_seconds < sum(value.estimate for value in state.timings.values())


def test_fanin_uses_elapsed_span_instead_of_sum_of_worker_durations() -> None:
    """
    Keep the measured optimization target separate from total compute consumption.

    Returns:
        None: Parallel workers contribute a shared stage span with independently retained test work.
    """
    value = selected()
    reports = [evolve(report, elapsed=100) for report in reports_for(value)]
    _, sample = aggregate(value, "digest", reports, elapsed=120)
    assert sample.wall_seconds == 120 and sample.test_seconds == 301
    with pytest.raises(ValueError, match="shorter"):
        aggregate(value, "digest", reports, elapsed=99)
