"""
Stream intent evidence only through admitted memory pipes using the existing native client.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

from witful.codegraph.cli import require_pipe
from witful.collection.protection import require_protected
from witful.context.models import Limits
from witful.exceptions import NativeError, StorageProtectionError
from witful.intent.models import Query, Review, State
from witful.knowledge.contracts import as_data
from witful.native.client import Client
from witful.native.models import parse
from witful.repertoire.models import Inventory

if TYPE_CHECKING:
    import argparse


def execute(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """
    Dispatch a typed operation with no staging, login, publication helper or implicit review.

    Args:
        args (argparse.Namespace): Parsed leaf namespace.
        parser (argparse.ArgumentParser): Owning leaf parser.

    Returns:
        int: Zero for complete discovery or durable mutation; nonzero for blocked or incomplete output.
    """
    del parser
    try:
        require_protected(args.client)
        require_pipe(sys.stdout.fileno())
        client = Client.load(args.client)
        operation: str = args.handler.name
        arguments: dict[str, object]
        if operation in {"publish", "review"}:
            require_pipe(sys.stdin.fileno())
            raw = sys.stdin.buffer.read(client.settings.max_bytes + 1)
            if len(raw) > client.settings.max_bytes:
                raise NativeError("incomplete")
            proposal: object = json.loads(raw)
            key = "state" if operation == "publish" else "decision"
            proposal = as_data(parse(proposal, State)) if operation == "publish" else as_data(parse(proposal, Review))
            if operation == "review" and args.initial:
                raise NativeError("invalid")
            arguments = {"operation": args.operation, "expected": args.expected, key: proposal}
        else:
            limits = as_data(
                Limits(nodes=args.nodes, edges=args.edges, tokens=args.tokens, text_bytes=args.bytes, elapsed_ms=args.elapsed_ms)
            )
            if operation == "draft":
                require_pipe(sys.stdin.fileno())
                raw = sys.stdin.buffer.read(client.settings.max_bytes + 1)
                if len(raw) > client.settings.max_bytes:
                    raise NativeError("incomplete")
                arguments = {"inventory": as_data(parse(json.loads(raw), Inventory)), "limits": limits}
            elif operation == "source":
                arguments = {"anchor": args.value, "digest": args.digest, "start": args.start, "end": args.end, "limits": limits}
            else:
                query = parse(
                    {
                        "operation": operation,
                        "value": args.value,
                        "view": args.view,
                        "history": args.history,
                        "changed": args.changed,
                        "required": args.required,
                        "action": args.action,
                    },
                    Query,
                )
                arguments = {"query": as_data(query), "limits": limits}
                operation = "query"
        result = client.invoke("intent-" + operation, arguments)
        print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
        return 1 if isinstance(result, dict) and result.get("result") in {"blocked", "incomplete"} else 0
    except (NativeError, StorageProtectionError, OSError, ValueError):
        print("Intent operation blocked: verify keys, admission, source bindings, pipes and budgets.", file=sys.stderr)
        return 1
