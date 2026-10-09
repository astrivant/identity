"""
Export reviewed knowledge, synchronize it through MCP, or save generated review proposals.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from jsonschema import ValidationError

from witful.files import replace_file
from witful.knowledge.contracts import as_data, schema, structure
from witful.sapience.models import Brief, Projection
from witful.sapience.projection import digest, project

if TYPE_CHECKING:
    from collections.abc import Sequence


def _write(path: Path, data: dict[str, object]) -> None:
    """
    Write an inspectable local artifact without touching source journals.

    Args:
        path (Path): Requested output, normally under ignored .witful.
        data (dict[str, object]): JSON-compatible projection or proposal.

    Returns:
        None: The destination is atomically replaced against its observed contents.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    replace_file(path, (json.dumps(data, indent=2, sort_keys=True) + "\n").encode(), expected=path.read_bytes() if path.exists() else None)


async def _remote(args: argparse.Namespace, projection: Projection | None) -> dict[str, object]:
    """
    Keep optional MCP imports and remote effects out of offline export operations.

    Args:
        args (argparse.Namespace): Parsed explicit command and server options.
        projection (Projection | None): Reviewed local data for sync, absent for a proposal request.

    Returns:
        dict[str, object]: Confirmed count or a pending generated proposal with retrieval provenance.

    Raises:
        ValueError: Required capabilities or proposal provenance do not match the request.
    """
    from witful.sapience.client import connect, connect_http, contracts, decode, synchronize

    if args.url and args.server_arg:
        raise ValueError("--server-arg applies only to stdio servers")
    connection = (
        connect_http(args.url, args.token_env, allow_insecure_http=args.allow_insecure_http)
        if args.url
        else connect([args.server, *args.server_arg])
    )
    async with connection as session:
        if projection is not None:
            return {"confirmed": await synchronize(session, projection)}

        schemas = await contracts(session)

        if "get_context_brief" not in schemas:
            raise ValueError("Sapience lacks a structured context brief contract")

        result = await session.call_tool("get_context_brief", {"topic": args.topic, "namespace": args.namespace})
        brief = structure(decode(result, schemas["get_context_brief"]), Brief)

        if brief.namespace != args.namespace or brief.topic != args.topic or brief.memory_count != len(brief.memory_ids):
            raise ValueError("Sapience brief provenance differs from the request")

        data = as_data(brief)
        return {
            "version": 1,
            "status": "pending-review",
            "producer": "sapience",
            "brief": data,
            "sha256": digest(data),
            "received_at": datetime.now(UTC).isoformat(),
        }


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run opt-in projection commands, leaving journals unchanged even after model synthesis.

    Args:
        argv (Sequence[str] | None): Explicit arguments or the process command line.

    Returns:
        int: Zero on success; argparse exits two with a content-safe diagnostic on failure.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("schema")

    for name in ("export", "sync", "propose"):
        command = commands.add_parser(name)
        command.add_argument("--namespace", required=True)
        command.add_argument("--output", type=Path)

        if name != "propose":
            command.add_argument("--collection-id", required=True)

        if name != "export":
            transport = command.add_mutually_exclusive_group(required=True)
            transport.add_argument("--server", help="Trusted executable path, launched without a shell")
            transport.add_argument("--url", help="Authenticated MCP endpoint for a shared identity service")
            command.add_argument("--token-env", default="WITFUL_SAPIENCE_TOKEN", help="Bearer token environment variable name")
            command.add_argument("--allow-insecure-http", action="store_true", help="Explicitly permit non-loopback plaintext HTTP")
            command.add_argument("--server-arg", action="append", default=[])

        if name == "propose":
            command.add_argument("--topic", required=True)

    args = parser.parse_args(argv)

    try:
        if args.command == "schema":
            print(json.dumps(schema(Projection), indent=2))
            return 0

        if not args.namespace or "*" in args.namespace or any(char.isspace() for char in args.namespace):
            raise ValueError("A concrete namespace is required")

        projection = None if args.command == "propose" else project(args.repo, args.collection_id, args.namespace)

        if args.command == "export":
            assert projection is not None
            data = as_data(projection)
        else:
            data = asyncio.run(_remote(args, projection))

        if args.command == "sync":
            print(json.dumps(data))
            return 0

        default = ".witful/sapience-projection.json" if args.command == "export" else f".witful/proposals/{data['sha256']}.json"
        output = args.repo / (args.output or Path(default))
        resolved = output.resolve()
        sources = (args.repo / "knowledge").resolve()

        # A generated artifact may never replace a reviewed source, even through a symlink.
        if resolved == (args.repo / "lessons.jsonl").resolve() or resolved == sources or sources in resolved.parents:
            raise ValueError("Projection output must be outside reviewed source paths")

        _write(output, data)
        print(output)

    except ImportError:
        parser.exit(2, "sapience: install the optional transport with pip install 'witful[sapience]'\n")
    except (OSError, ValueError, ValidationError, RuntimeError, ExceptionGroup):
        parser.exit(
            2, "sapience: source, transport, or response validation failed; check the config and server; journals remain unchanged\n"
        )

    return 0
