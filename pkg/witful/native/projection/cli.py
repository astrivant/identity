"""
Run one bounded, cancellable projection scheduling cycle using only the controller's mutually authenticated client interface.
"""

from __future__ import annotations

import json
import signal
import sys
import time
from threading import Event
from typing import TYPE_CHECKING

from attrs import evolve

from witful.collection.protection import require_protected
from witful.exceptions import NativeError, StorageProtectionError
from witful.native.client import Client
from witful.native.wire import integer, mapping, sequence, text

if TYPE_CHECKING:
    import argparse
    from types import FrameType


def execute(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """
    Poll the configured policy and attempt due work within its retry budget, preserving interruption and incomplete outcomes.

    Args:
        args (argparse.Namespace): Selected recursive CLI leaf arguments.
        parser (argparse.ArgumentParser): Owning parser for invalid cycle budgets.

    Returns:
        int: Zero for a completed or deliberately deferred cycle, nonzero for unresolved delivery, and signal-specific cancellation.
    """
    if args.seconds < 1:
        parser.error("--seconds must be positive")
    cancelled = Event()
    exit_code = 0
    deadline = time.monotonic() + args.seconds
    previous = {kind: signal.getsignal(kind) for kind in (signal.SIGINT, signal.SIGTERM)}

    def stop(kind: int, frame: FrameType | None) -> None:
        """
        Stop admitting new requests and interrupt backoff while preserving the received cancellation status.

        Args:
            kind (int): Actual operating-system signal.
            frame (FrameType | None): Interpreter-owned signal context, never retained.

        Returns:
            None: The bounded current transport call can settle; no subsequent attempt starts.
        """
        nonlocal exit_code
        exit_code = 128 + kind
        cancelled.set()

    for kind in previous:
        signal.signal(kind, stop)
    try:
        require_protected(args.client)
        client = Client.load(args.client)

        def call(operation: str, arguments: object) -> object:
            """
            Refuse new calls after cancellation or exhaustion and clamp each transport deadline to the remaining cycle.

            Args:
                operation (str): Package-owned controller endpoint.
                arguments (object): Explicit bounded wire arguments.

            Returns:
                object: One actual response without implicit transport retries.
            """
            remaining = int(deadline - time.monotonic())
            if cancelled.is_set() or remaining < 1:
                raise NativeError("incomplete")
            bounded = evolve(client, settings=evolve(client.settings, timeout=min(remaining, client.settings.timeout)))
            return bounded.invoke(operation, arguments)

        snapshot = mapping(call("project-status", {}), {"queue_size", "queue_bytes", "oldest_seconds", "pending", "verified", "policy"})
        policy = mapping(snapshot["policy"], {"mode", "attempts", "retry_seconds", "retry_max_seconds", "targets"})
        targets = tuple(text(item) for item in sequence(policy["targets"]))
        attempts, initial, maximum = (integer(policy[key]) for key in ("attempts", "retry_seconds", "retry_max_seconds"))
        if min(attempts, initial, maximum) < 1 or initial > maximum:
            raise NativeError("invalid")
        results: list[dict[str, object]] = []
        for target in targets:
            state = "waiting"
            for attempt in range(attempts):
                raw = call("project-drain", {"target": target, "scheduled": True})
                if not isinstance(raw, dict) or not isinstance(raw.get("state"), str):
                    raise NativeError("invalid")
                state = raw["state"]
                if state in {"idle", "disabled", "manual", "waiting", "blocked", "diverged"}:
                    break
                if state not in {"unknown", "projection_pending", "remote_verified"}:
                    raise NativeError("invalid")
                if state != "remote_verified" and attempt + 1 < attempts:
                    delay = min(maximum, initial * 2 ** min(attempt, maximum.bit_length()))
                    cancelled.wait(min(delay, max(0.0, deadline - time.monotonic())))
            results.append({"target": target, "state": state})
            if state in {"unknown", "blocked", "diverged", "projection_pending"}:
                exit_code = exit_code or 1
        final = mapping(call("project-status", {}), {"queue_size", "queue_bytes", "oldest_seconds", "pending", "verified", "policy"})
        remaining_work = integer(final["queue_size"])
        if remaining_work > 0 and any(item["state"] == "remote_verified" for item in results):
            exit_code = exit_code or 1
        print(json.dumps({"targets": results, "queue_size": remaining_work, "cancelled": cancelled.is_set()}, ensure_ascii=True))
        return exit_code
    except (NativeError, OSError, ValueError, StorageProtectionError):
        print("Projection cycle incomplete", file=sys.stderr)
        return exit_code or 1
    finally:
        for kind, handler in previous.items():
            signal.signal(kind, handler)
