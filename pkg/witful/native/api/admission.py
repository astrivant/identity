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
        active (int): Requests currently executing in this worker.
        rejected (int): Refusals due to admission pressure.
        failures (int): Completed failed requests.
        completed (int): Completed admitted requests.
        seconds (float): Aggregate admitted request duration.
        draining (bool): Shutdown state preventing new admission.
        dependencies (dict[str, float]): Last bounded readiness probe timings by fixed dependency name.
    """

    limit: int
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
        if type(self.limit) is not int or self.limit < 1:
            raise NativeError("invalid")

    def acquire(self) -> bool:
        """
        Admit one request without waiting on an application queue.

        Returns:
            bool: Whether ownership was acquired.
        """
        with self._lock:
            if self.draining or self.active >= self.limit:
                self.rejected += 1
                return False
            self.active += 1
            return True

    def release(self, seconds: float, failed: bool) -> None:
        """
        Release exactly one owned request and update bounded aggregate metrics.

        Args:
            seconds (float): Measured elapsed request time.
            failed (bool): Whether the response indicated failure.

        Returns:
            None: Ownership and local counters are updated.
        """
        with self._lock:
            self.active -= 1
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
                "completed": self.completed,
                "failures": self.failures,
                "rejected": self.rejected,
                "request_seconds": self.seconds,
                "status": "draining" if self.draining else "serving",
                "dependency_seconds": dict(self.dependencies),
            }
