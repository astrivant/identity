"""
Measure a bounded synthetic single-writer comparison with a local-Git baseline registered before the PostgreSQL candidate.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import random
import resource
import statistics
import subprocess
import time
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from witful.native.git import Git

from tests.native.runtime import lesson

if TYPE_CHECKING:
    from collections.abc import Callable

    from tests.native.runtime import Runtime


ROOT = Path(__file__).resolve().parents[2]


def timed(action: Callable[[], object]) -> float:
    """
    Measure one complete accepted service operation, including authority and cryptographic work.

    Args:
        action (Callable[[], object]): Actual service call with explicit synthetic inputs.

    Returns:
        float: Monotonic elapsed milliseconds; failures remain test failures rather than omitted samples.
    """
    start = time.perf_counter_ns()
    action()
    return (time.perf_counter_ns() - start) / 1_000_000


def p95(values: list[float]) -> float:
    """
    Return the conservative nearest-rank percentile without interpolating observations.

    Args:
        values (list[float]): Nonempty raw latency samples.

    Returns:
        float: Nearest-rank 95th percentile in the sample's units.
    """
    return sorted(values)[max(0, (95 * len(values) + 99) // 100 - 1)]


def summarize(values: list[float]) -> dict[str, object]:
    """
    Retain measured quantiles and a reproducible bootstrap interval with its small-sample limitation.

    Args:
        values (list[float]): Raw successful operation latencies.

    Returns:
        dict[str, object]: Raw samples, observed percentiles and a seeded bootstrap interval for p95.
    """
    rng = random.Random(0)
    bootstrap = sorted(p95(rng.choices(values, k=len(values))) for _ in range(1000))
    return {
        "samples_ms": values,
        "p50_ms": statistics.median(values),
        "p95_ms": p95(values),
        "p99_ms": max(values),
        "p95_bootstrap_95_ms": [bootstrap[24], bootstrap[974]],
    }


def append_percentile(profile: object) -> float:
    """
    Read a measured append percentile without treating unvalidated JSON as a typed result.

    Args:
        profile (object): Persisted or current profile observations.

    Returns:
        float: Positive measured append p95 in milliseconds.
    """
    assert isinstance(profile, dict)
    observations = profile["observations"]
    assert isinstance(observations, dict)
    append = observations["append"]
    assert isinstance(append, dict)
    value = append["p95_ms"]
    assert isinstance(value, int | float) and value > 0
    return float(value)


@pytest.mark.skipif(os.environ.get("WITFUL_NATIVE_BENCHMARK") != "1", reason="Explicit bounded synthetic performance experiment")
def test_registered_local_git_comparison(runtime: Runtime) -> None:
    """
    Compare actual protected native operations at matched local fsync/WAL durability without claiming hosted-provider or HA equivalence.

    Args:
        runtime (Runtime): Real local Git or PostgreSQL with independent authority and transient synthetic custody.

    Returns:
        None: Raw trials and a fixed-before-candidate threshold report are retained; a missed performance target is recorded honestly.
    """
    directory = Path(os.environ["WITFUL_NATIVE_EVIDENCE"])
    directory.mkdir(parents=True, exist_ok=True)
    name = "git" if isinstance(runtime.service.store, Git) else "postgres"
    output = directory / ("benchmark-" + name + ".json")
    assert not output.exists(), "Preserve prior trials; choose a fresh experiment directory"
    paths = sorted((ROOT / "pkg/witful/native").rglob("*.py")) + [Path(__file__)]
    source_digest = hashlib.sha256(b"".join(str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes() for path in paths)).hexdigest()
    source = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, check=True, text=True).stdout.strip()
    plan = directory / "benchmark-preregistration.json"
    if name == "postgres":
        contract = json.loads(plan.read_text())
        assert contract["source_digest"] == source_digest
        baseline = directory / "benchmark-git.json"
        assert contract["baseline_sha256"] == hashlib.sha256(baseline.read_bytes()).hexdigest()
    service, access = runtime.service, runtime.access
    depths = (16, 64)
    trials = 8
    profiles: list[dict[str, object]] = []
    cpu = time.process_time()
    for depth in depths:
        ref = "depth-" + str(depth)
        service.append(access, str(uuid4()), ref, None, tuple(lesson(f"synthetic-benchmark-{depth}-{index}") for index in range(depth)))
        head = service.history(access, ref)[-1][0].id
        cold_read = timed(partial(service.read, access, head))
        for _ in range(3):
            service.read(access, head)
        values: dict[str, list[float]] = {key: [] for key in ("exact_read", "head", "history", "append", "branch")}
        for trial in range(trials):
            values["exact_read"].append(timed(partial(service.read, access, head)))
            values["head"].append(timed(partial(service.snapshot, access, "read", "*")))
            values["history"].append(timed(partial(service.history, access, ref)))
            entry = lesson(f"synthetic-benchmark-{depth}-append-{trial}")
            operation = str(uuid4())
            values["append"].append(timed(partial(service.append, access, operation, ref, head, (entry,))))
            head = service.history(access, ref)[-1][0].id
            branch = f"trial-{depth}-{trial}"
            values["branch"].append(timed(partial(service.branch, access, str(uuid4()), branch, head)))
        profiles.append(
            {
                "initial_branch_depth": depth,
                "cold_exact_read_ms": cold_read,
                "observations": {key: summarize(samples) for key, samples in values.items()},
            }
        )
    data = {
        "schema": 1,
        "backend": name,
        "source": source,
        "source_digest": source_digest,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_seconds": time.process_time() - cpu,
        "max_rss_platform_units": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "writers": 1,
        "trials_per_profile": trials,
        "warmup_reads": 3,
        "profiles": profiles,
        "durability": "local fsync/WAL on; shared independent PostgreSQL authority; no remote projection",
        "custody": "real RSA/AES/Ed25519 with transient in-process synthetic keys; broker network excluded",
        "exclusions": [
            "hosted Git latency",
            "synchronous replica performance",
            "network key-service latency",
            "large histories",
            "multi-writer contention",
            "fork/split/merge timing",
            "cache hits",
            "production cost",
        ],
        "limitations": (
            "branch depths share a growing identity frontier; short-run p99 is sample maximum; bootstrap is not a population guarantee"
        ),
    }
    if name == "postgres":
        baseline_data = json.loads((directory / "benchmark-git.json").read_text())
        ratios = [
            append_percentile(candidate) / append_percentile(base)
            for candidate, base in zip(profiles, baseline_data["profiles"], strict=True)
        ]
        data["decision"] = {
            "append_p95_ratios": ratios,
            "required_max_ratio": contract["append_p95_max_ratio"],
            "target_met": all(ratio <= contract["append_p95_max_ratio"] for ratio in ratios),
            "scope": "local comparison only; no hosted-Git performance or backend selection conclusion",
        }
    with output.open("x") as destination:
        json.dump(data, destination, indent=2)
        destination.write("\n")
    if name == "git":
        with plan.open("x") as destination:
            json.dump(
                {
                    "schema": 1,
                    "source_digest": source_digest,
                    "baseline_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                    "append_p95_max_ratio": 0.70,
                    "rule": "Every declared local profile must reduce append p95 by at least 30 percent",
                    "registered_after_baseline_before_candidate": True,
                },
                destination,
                indent=2,
            )
            destination.write("\n")
