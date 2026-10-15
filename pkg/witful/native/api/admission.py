"""
Own bounded request admission and non-sensitive local operational snapshots.
"""

from __future__ import annotations

from threading import Lock

from attrs import define, field

from witful.exceptions import NativeError


@define
class Admission:
    """
    Refuse excess work immediately instead of accumulating an unbounded implicit application queue.

    Attributes:
        limit (int): Maximum concurrently owned requests per worker process.
        recovery_limit (int): Separately reserved bounded recovery/cancellation requests.
        recovering (int): Currently executing reserved recovery requests.
        active (int): All requests currently executing in this worker.
        rejected (int): Refusals due to admission pressure.
        failures (int): Completed failed requests.
        completed (int): Completed admitted requests.
        seconds (float): Aggregate admitted request duration.
        draining (bool): Shutdown state preventing new admission.
        dependencies (dict[str, float]): Last bounded readiness probe timings by fixed dependency name.
    """

    limit: int
    recovery_limit: int = 1
    recovering: int = 0
    active: int = 0
    rejected: int = 0
    failures: int = 0
    completed: int = 0
    seconds: float = 0.0
    draining: bool = False
    dependencies: dict[str, float] = field(factory=dict)
    _lock: Lock = field(factory=Lock, repr=False)

    def __attrs_post_init__(self) -> None:
        """
        Require an explicit positive admission limit.

        Returns:
            None: The configured limit is valid.
        """
        if any(type(value) is not int or value < 1 for value in (self.limit, self.recovery_limit)):
            raise NativeError("invalid")

    def acquire(self, recovery: bool = False) -> bool:
        """
        Admit one request without letting saturated execution consume the reserved recovery budget.

        Args:
            recovery (bool): Whether this is a server-selected recovery/cancellation route.

        Returns:
            bool: Whether ownership was acquired.
        """
        with self._lock:
            saturated = self.recovering >= self.recovery_limit if recovery else self.active - self.recovering >= self.limit
            if self.draining or saturated:
                self.rejected += 1
                return False
            self.active += 1
            self.recovering += int(recovery)
            return True

    def release(self, seconds: float, failed: bool, recovery: bool = False) -> None:
        """
        Release exactly one owned request and update bounded aggregate metrics.

        Args:
            seconds (float): Measured elapsed request time.
            failed (bool): Whether the response indicated failure.
            recovery (bool): The server-selected budget originally acquired for this request.

        Returns:
            None: Ownership and local counters are updated.
        """
        with self._lock:
            self.active -= 1
            self.recovering -= int(recovery)
            self.completed += 1
            self.failures += int(failed)
            self.seconds += max(0.0, seconds)

    def stop(self) -> None:
        """
        Make repeated shutdown admission stops safe.

        Returns:
            None: New requests will be refused; the runtime drains owned requests.
        """
        with self._lock:
            self.draining = True

    def observe(self, dependency: str, seconds: float) -> None:
        """
        Keep only fixed non-sensitive dependency labels.

        Args:
            dependency (str): One of authority, storage or broker.
            seconds (float): Actual measured operation duration.

        Returns:
            None: Last observed dependency duration is available locally.
        """
        if dependency not in {"authority", "storage", "broker"}:
            raise NativeError("invalid")
        with self._lock:
            self.dependencies[dependency] = max(0.0, seconds)

    def snapshot(self) -> dict[str, object]:
        """
        Return a local snapshot without credentials, record labels or dependency calls.

        Returns:
            dict[str, object]: Owned work, counters, bounded status and actual last probe timings.
        """
        with self._lock:
            return {
                "queue_size": 0,
                "in_flight": self.active,
                "admission_limit": self.limit,
                "recovery_limit": self.recovery_limit,
                "recovery_in_flight": self.recovering,
                "completed": self.completed,
                "failures": self.failures,
                "rejected": self.rejected,
                "request_seconds": self.seconds,
                "status": "draining" if self.draining else "serving",
                "dependency_seconds": dict(self.dependencies),
            }
