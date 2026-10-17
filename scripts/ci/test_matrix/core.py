"""
Balance measured test costs and apply damped PID feedback at complete-run boundaries.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from test_matrix.models import Plan, Sample, State, Timing

if TYPE_CHECKING:
    from test_matrix.models import Report, Settings


def update(previous: Timing | None, observed: float) -> Timing:
    """
    Update a duration estimate with deadband, slew limiting and conditional integration.

    Args:
        previous (Timing | None): Prior accepted estimate, absent on cold start.
        observed (float): Positive finite measured duration.

    Returns:
        Timing: Prediction bounded to a 25 percent change per accepted run.
    """
    if not math.isfinite(observed) or observed <= 0:
        raise ValueError("Test duration must be finite and positive")
    if previous is None:
        return Timing(observed)
    error = observed - previous.estimate
    if abs(error) <= previous.estimate * 0.05:
        return Timing(previous.estimate)
    integral = max(-previous.estimate, min(previous.estimate, previous.integral + error))
    delta = 0.5 * error + 0.05 * integral + 0.1 * (error - previous.error)
    limit = previous.estimate * 0.25
    if abs(delta) > limit and delta * error > 0:
        integral = previous.integral
        delta = 0.5 * error + 0.05 * integral + 0.1 * (error - previous.error)
    estimate = previous.estimate + max(-limit, min(limit, delta))
    return Timing(estimate, error, max(-estimate, min(estimate, integral)))


def partition(nodes: list[str], timings: dict[str, Timing], count: int, default: float) -> list[list[str]]:
    """
    Place expensive tests first with stable lexical tie-breaking and one owner per test.

    Args:
        nodes (list[str]): Unique collected node IDs.
        timings (dict[str, Timing]): Compatible predictions.
        count (int): Positive runner count no greater than test count.
        default (float): Estimate for newly collected tests.

    Returns:
        list[list[str]]: Deterministic nonempty partitions sorted for stable execution.
    """
    if not nodes or len(nodes) != len(set(nodes)) or not 1 <= count <= len(nodes):
        raise ValueError("Partitions require unique tests and useful positive runner count")
    result: list[list[str]] = [[] for _ in range(count)]
    loads = [0.0] * count
    for node in sorted(nodes, key=lambda item: (-timings.get(item, Timing(default)).estimate, item)):
        selected = min(range(count), key=lambda index: (loads[index], index))
        result[selected].append(node)
        loads[selected] += timings.get(node, Timing(default)).estimate
    return [sorted(items) for items in result]


def plan(nodes: list[str], state: State, settings: Settings, repository: str, source: str, run: str, started_at: float = 0.0) -> Plan:
    """
    Select a bounded dynamic matrix from measured costs, keeping small suites on one runner.

    Args:
        nodes (list[str]): Complete collected pytest node IDs.
        state (State): Validated compatible prior feedback, or an explicit cold start.
        settings (Settings): Operator's runner and duration budgets.
        repository (str): Repository namespace.
        source (str): Exact checkout revision.
        run (str): Run identifier and attempt.
        started_at (float): Planner job start timestamp, supplied externally.

    Returns:
        Plan: Frozen plan; empty or invalid input is rejected rather than silently skipping verification.
    """
    if (
        settings.threshold < 1
        or not 1 <= settings.maximum <= 256
        or settings.workers < 1
        or not 0 <= settings.tolerance < 1
        or not math.isfinite(settings.default_seconds)
        or settings.default_seconds <= 0
    ):
        raise ValueError("Invalid test matrix resource policy")
    for value in [*state.timings.values(), *state.overheads.values()]:
        if not all(math.isfinite(v) for v in (value.estimate, value.error, value.integral)) or value.estimate <= 0:
            raise ValueError("Invalid cached feedback")
    costs = {node: state.timings[node] for node in nodes if node in state.timings}
    count = 1
    overhead = state.overheads.get(str(state.shards), Timing(0.001)).estimate
    candidates: dict[int, float] = {}
    if len(nodes) > settings.threshold:
        if not costs:
            count = math.ceil(len(nodes) / settings.threshold)
        else:
            # Search a discrete, budgeted domain. Parallel intervals contribute their maximum, never their sum.
            for candidate in range(2, min(settings.maximum, len(nodes)) + 1):
                groups = partition(nodes, costs, candidate, settings.default_seconds)
                candidates[candidate] = (
                    work_time(groups, costs, settings.workers, settings.default_seconds)
                    + state.overheads.get(str(candidate), Timing(overhead)).estimate
                )
            if candidates:
                best = min(candidates.values())
                desired = min(number for number, seconds in candidates.items() if seconds <= best * (1 + settings.tolerance))
                old = max(2, min(settings.maximum, state.shards))
                count = old if candidates[old] <= best * (1 + settings.tolerance) else max(old - 1, min(old + 1, desired))
        count = max(1, min(settings.maximum, len(nodes), count))
    groups = partition(nodes, costs, count, settings.default_seconds)
    predicted = (
        work_time(groups, costs, settings.workers, settings.default_seconds) + state.overheads.get(str(count), Timing(overhead)).estimate
    )
    return Plan(
        1, repository, source, run, state.scope, settings, groups, costs, dict(state.overheads), started_at, predicted if costs else None
    )


def work_time(groups: list[list[str]], timings: dict[str, Timing], workers: int, default: float) -> float:
    """
    Estimate the parallel critical path using feasible assignments at both runner and worker tiers.

    Args:
        groups (list[list[str]]): Runner-owned tests.
        timings (dict[str, Timing]): Explicit test duration estimates.
        workers (int): Processes per runner.
        default (float): Fallback duration for new tests.

    Returns:
        float: Slowest modeled runner, bounded below by its longest indivisible test.
    """
    elapsed = []
    for group in groups:
        slots = [0.0] * min(workers, len(group))
        for node in sorted(group, key=lambda item: (-timings.get(item, Timing(default)).estimate, item)):
            slot = min(range(len(slots)), key=lambda index: (slots[index], index))
            slots[slot] += timings.get(node, Timing(default)).estimate
        elapsed.append(max(slots))
    return max(elapsed)


def aggregate(selected: Plan, digest: str, reports: list[Report], elapsed: float | None = None) -> tuple[State, Sample]:
    """
    Accept feedback only after exact plan coverage and successful terminal results from every worker.

    Args:
        selected (Plan): Immutable source-bound plan.
        digest (str): Expected plan digest.
        reports (list[Report]): Worker reports downloaded from this run only.
        elapsed (float | None): Measured planner-through-fan-in wall time; omitted only for isolated tests.

    Returns:
        tuple[State, Sample]: Pruned next-run state and public aggregate measurement.
    """
    expected = set(range(len(selected.partitions)))
    if len(reports) != len(expected) or {report.shard for report in reports} != expected:
        raise ValueError("Missing, duplicate or unexpected shard report")
    state: dict[str, Timing] = {}
    total, error, measured, skipped = 0.0, 0.0, 0, 0
    for report in sorted(reports, key=lambda item: item.shard):
        if report.plan_sha256 != digest or report.exit_code != 0 or set(report.results) != set(selected.partitions[report.shard]):
            raise ValueError("Failed or mismatched test coverage")
        if not math.isfinite(report.elapsed) or report.elapsed <= 0:
            raise ValueError("Invalid worker duration")
        for node, result in report.results.items():
            if result.outcome not in {"passed", "skipped"} or not math.isfinite(result.seconds) or result.seconds < 0:
                raise ValueError("Invalid test result")
            previous = selected.timings.get(node)
            # Skips are coverage evidence, not execution-cost training data.
            if result.outcome == "skipped":
                skipped += 1
                if previous is not None:
                    state[node] = previous
                continue
            observed = max(result.seconds, 0.000001)
            state[node] = update(previous, observed)
            total += observed
            if previous is not None:
                error += abs(observed - previous.estimate)
                measured += 1
    wall = max(report.elapsed for report in reports) if elapsed is None else elapsed
    if not math.isfinite(wall) or wall < max(report.elapsed for report in reports):
        raise ValueError("Elapsed stage time cannot be shorter than an individual worker")
    actual = {node: Timing(max(result.seconds, 0.000001)) for report in reports for node, result in report.results.items()}
    overhead = max(0.001, wall - work_time(selected.partitions, actual, selected.settings.workers, selected.settings.default_seconds))
    overheads = dict(selected.overheads)
    overheads[str(len(reports))] = update(overheads.get(str(len(reports))), overhead)
    sample = Sample(
        1,
        selected.repository,
        selected.source,
        selected.run,
        selected.scope,
        digest,
        sum(map(len, selected.partitions)),
        skipped,
        len(reports),
        selected.settings.workers,
        wall,
        total,
        error if measured else None,
        measured,
        selected.predicted_seconds,
        overhead,
    )
    return State(selected.scope, state, len(reports), overheads), sample
