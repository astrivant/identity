"""
Join a child that receives the supervisor's process-group signal before flushing a final parent record.
"""

from __future__ import annotations

import signal
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import FrameType


def stopped(number: int, frame: FrameType | None) -> None:
    """
    Leave child collection to the ordinary wait path rather than forwarding the signal twice.

    Args:
        number (int): Signal delivered directly to the parent and child process group.
        frame (FrameType | None): Interrupted frame, intentionally not inspected.

    Returns:
        None: The parent continues waiting for the child's final write and exit.
    """


for stop_signal in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
    signal.signal(stop_signal, stopped)

# The child emits readiness only after both generations have installed their handlers.
with subprocess.Popen([sys.executable, str(Path(__file__).with_name("workload.py")), sys.argv[1]]) as child:
    result = child.wait()

if result:
    raise SystemExit(result)

Path("joined.md").write_text("Child joined before snapshot.\n")
