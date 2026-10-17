"""
Define closed, versioned planning and measurement contracts for CI test workers.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, TypeVar

from attrs import field, frozen
from cattrs import Converter

if TYPE_CHECKING:
    from pathlib import Path

T = TypeVar("T")
CONVERTER = Converter(forbid_extra_keys=True)


@frozen
class Settings:
    """
    Bound hosted resource use independently of the size of the test suite.

    Attributes:
        threshold (int): Suites at or below this size use one runner.
        maximum (int): Operator budget for concurrent runners, at most GitHub's matrix limit.
        workers (int): Pytest workers per runner.
        tolerance (float): Fractional completion-time equivalence window for preferring fewer runners.
        default_seconds (float): Cold prediction for a new test.
    """

    threshold: int = 300
    maximum: int = 8
    workers: int = 4
    tolerance: float = 0.05
    default_seconds: float = 1.0


@frozen
class Timing:
    """
    Retain bounded PID prediction state for an individual collected test.

    Attributes:
        estimate (float): Predicted seconds including setup and teardown.
        error (float): Last observed minus predicted duration.
        integral (float): Accumulated prediction error with anti-windup.
    """

    estimate: float
    error: float = 0.0
    integral: float = 0.0


@frozen
class State:
    """
    Cache feedback only within one repository, lockfile, runner and controller configuration.

    Attributes:
        scope (str): Compatibility digest, not a moving source revision.
        timings (dict[str, Timing]): Prior complete-run cost estimates.
        shards (int): Previously selected runner count for slew limiting.
        overheads (dict[str, Timing]): Critical-path overhead prediction indexed by runner count.
    """

    scope: str
    timings: dict[str, Timing] = field(factory=dict)
    shards: int = 1
    overheads: dict[str, Timing] = field(factory=dict)


@frozen
class Plan:
    """
    Freeze every test's single owner before any matrix worker executes.

    Attributes:
        version (int): Plan format version.
        repository (str): Hosted namespace, separating fork evidence.
        source (str): Immutable source revision.
        run (str): Pipeline identifier and attempt.
        scope (str): Feedback compatibility digest.
        settings (Settings): Effective resource policy.
        partitions (list[list[str]]): Disjoint sorted pytest node IDs for each runner.
        timings (dict[str, Timing]): Estimates used for this decision.
        overheads (dict[str, Timing]): Accepted per-count critical-path overhead estimates.
        started_at (float): Planner job start supplied at the orchestration boundary.
        predicted_seconds (float | None): Predicted elapsed stage time, absent on cold start.
    """

    version: int
    repository: str
    source: str
    run: str
    scope: str
    settings: Settings
    partitions: list[list[str]]
    timings: dict[str, Timing]
    overheads: dict[str, Timing]
    started_at: float
    predicted_seconds: float | None


@frozen
class Result:
    """
    Capture all phases of one test without logs or captured payloads.

    Attributes:
        seconds (float): Summed setup, call and teardown durations.
        outcome (str): Passed, skipped or failed.
    """

    seconds: float
    outcome: str


@frozen
class Report:
    """
    Bind a worker's terminal result to the exact frozen plan.

    Attributes:
        plan_sha256 (str): Digest of the downloaded plan bytes.
        shard (int): Zero-based owner index.
        exit_code (int): Pytest session exit code.
        elapsed (float): Worker pytest wall-clock seconds, excluding environment setup and scheduling.
        results (dict[str, Result]): Completed test phases by node ID.
    """

    plan_sha256: str
    shard: int
    exit_code: int
    elapsed: float
    results: dict[str, Result]


def load(path: Path, cls: type[T]) -> T:
    """
    Decode a closed model without treating malformed state as trusted feedback.

    Args:
        path (Path): Explicit JSON input.
        cls (type[T]): Expected model type.

    Returns:
        T: Structured model; malformed or extra fields raise a diagnostic.
    """
    return CONVERTER.structure(json.loads(path.read_bytes()), cls)


def write(path: Path, value: object) -> None:
    """
    Write canonical JSON after the caller validates the complete value.

    Args:
        path (Path): Explicit output location.
        value (object): Structured value to serialize.

    Returns:
        None: Sorted output has a final newline and its parent directory exists.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(CONVERTER.unstructure(value), sort_keys=True, indent=2, allow_nan=False) + "\n")


@frozen
class Sample:
    """
    Publish aggregate test scheduling evidence without logs or private runtime inputs.

    Attributes:
        version (int): Measurement format.
        repository (str): Owning repository namespace.
        source (str): Tested source commit.
        run (str): Run and attempt identifier.
        scope (str): Comparable controller environment.
        plan_sha256 (str): Digest of immutable assignment.
        tests (int): Complete collected count.
        skipped (int): Explicitly skipped tests.
        shards (int): Hosted runner count.
        workers (int): Pytest workers per runner.
        wall_seconds (float): Elapsed time from planner job start through successful fan-in; parallel intervals count once.
        test_seconds (float): Total measured phase seconds excluding skipped tests.
        prediction_error_seconds (float | None): Absolute error for previously measured tests, absent on cold start.
        predicted_tests (int): Tests contributing prediction error.
        predicted_seconds (float | None): Predicted elapsed completion time, absent on cold start.
        overhead_seconds (float): Observed stage time beyond modeled parallel test work.
    """

    version: int
    repository: str
    source: str
    run: str
    scope: str
    plan_sha256: str
    tests: int
    skipped: int
    shards: int
    workers: int
    wall_seconds: float
    test_seconds: float
    prediction_error_seconds: float | None
    predicted_tests: int
    predicted_seconds: float | None
    overhead_seconds: float
