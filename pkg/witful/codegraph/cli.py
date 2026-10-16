"""
Stream enrolled graph evidence only to an explicitly admitted in-memory consumer.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from typing import TYPE_CHECKING

from witful.collection.protection import require_protected
from witful.context.models import Limits
from witful.exceptions import NativeError, StorageProtectionError
from witful.knowledge.contracts import as_data
from witful.native.client import Client

if TYPE_CHECKING:
    import argparse


def require_pipe(descriptor: int) -> None:
    """
    Refuse terminal disclosure and durable plaintext file redirects.

    Args:
        descriptor (int): Output descriptor for the separately admitted memory consumer.

    Returns:
        None: The descriptor is a pipe or socket; recipient behavior still requires reviewed runtime admission.
    """
    mode = os.fstat(descriptor).st_mode
    if not (stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode)):
        raise NativeError("denied")


def execute(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """
    Send one explicitly selected operation to the admitted controller and memory-only output pipe.

    Args:
        args (argparse.Namespace): Parsed leaf arguments.
        parser (argparse.ArgumentParser): Owning leaf parser.

    Returns:
        int: Zero for a complete streamed result, otherwise a redacted nonzero status.
    """
    del parser
    try:
        require_protected(args.client)
        if not args.pipe:
            raise NativeError("denied")
        require_pipe(sys.stdout.fileno())
        client = Client.load(args.client)
        arguments: dict[str, object]
        if args.graph_operation == "build":
            arguments = {"operation": args.operation, "revision": args.revision, "expected": args.expected}
        elif args.graph_operation == "rotate":
            arguments = {"operation": args.operation, "mode": args.mode}
        elif args.graph_operation == "recover":
            arguments = {}
        else:
            arguments = {
                "revision": args.revision,
                "symbol": args.symbol,
                "direction": args.direction,
                "depth": args.depth,
                "limits": as_data(
                    Limits(nodes=args.nodes, edges=args.edges, tokens=args.tokens, text_bytes=args.bytes, elapsed_ms=args.elapsed_ms)
                ),
            }
        result = client.invoke("codegraph-" + args.graph_operation, arguments)
        # The signed runtime profile covers this recipient. No plaintext file or retained result cache is created here.
        print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
        return 0
    except (NativeError, StorageProtectionError, OSError):
        print("CodeGraph operation blocked: verify admission, keys, output pipe, source revision and budgets.", file=sys.stderr)
        return 1
