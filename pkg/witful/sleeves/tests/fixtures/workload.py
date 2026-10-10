"""
Flush one synthetic observation after a supervisor forwards a termination signal.
"""

from __future__ import annotations

import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import FrameType


def stopped(number: int, frame: FrameType | None) -> None:
    """
    Write the last observation before exiting gracefully.

    Args:
        number (int): Forwarded signal number.
        frame (FrameType | None): Interrupted execution frame.

    Returns:
        None: The process exits after its final durable file write.
    """
    Path("final.md").write_text("Flushed after signal.\n")
    raise SystemExit(0)


for stop_signal in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
    signal.signal(stop_signal, stopped)
with Path(sys.argv[1]).open("w") as ready:
    ready.write("ready")
signal.pause()
