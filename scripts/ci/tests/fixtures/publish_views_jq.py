#!/usr/bin/env python3
"""
Enforce a Linux-sized argument boundary before delegating to the real local jq.
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    """
    Reject oversized arguments consistently without contacting any external service.

    Returns:
        None: Replaces this process with jq or exits with the simulated argument-size failure.
    """
    if any(len(argument.encode()) >= 131_072 for argument in sys.argv[1:]):
        raise SystemExit("Argument list too long")

    executable = os.environ["QA_REAL_JQ"]
    os.execv(executable, [executable, *sys.argv[1:]])


if __name__ == "__main__":
    main()
