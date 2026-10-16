"""
Declare optional graph commands without importing SDK, database or controller runtimes.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from witful.commands.builder import Command


def setup(parser: argparse.ArgumentParser) -> None:
    """
    Declare explicit operator provisioning, optional for users of an existing native deployment.

    Args:
        parser (argparse.ArgumentParser): Setup leaf.

    Returns:
        None: Defaults apply only to this explicitly invoked setup command.
    """
    parser.add_argument("--directory", type=Path, required=True, help="Private protected setup directory outside Git")
    parser.add_argument("--account", required=True, help="Existing authenticated 1Password account")
    parser.add_argument("--vault", default="Witful CodeGraph Development", help="Dedicated vault name or ID to create or reuse")
    parser.add_argument(
        "--provision", action=argparse.BooleanOptionalAction, default=True, help="Create missing vault/items/account (default: on)"
    )
    parser.add_argument("--wrapping-reference", help="Existing op://VAULT_ID/ITEM_ID/FIELD with generation/kind fields")
    parser.add_argument("--signing-reference", help="Existing op://VAULT_ID/ITEM_ID/FIELD with generation/kind fields")
    parser.add_argument("--token-reference", help="Existing vault-scoped read-only service-account token field")


def common(parser: argparse.ArgumentParser) -> None:
    """
    Declare existing native client settings and an explicit admitted memory consumer.

    Args:
        parser (argparse.ArgumentParser): Command-owned parser.

    Returns:
        None: Shared options are registered once.
    """
    parser.add_argument("--client", type=Path, required=True, help="Existing mTLS native client configuration for the graph scope")
    parser.add_argument(
        "--pipe",
        action="store_true",
        required=True,
        help="Stream to the admitted non-logging consumer; regular files and terminals are refused",
    )


def build(parser: argparse.ArgumentParser) -> None:
    """
    Declare atomic build inputs and explicit prior generation.

    Args:
        parser (argparse.ArgumentParser): Build leaf.

    Returns:
        None: Expected-revision and stable retry inputs are required.
    """
    common(parser)
    parser.set_defaults(graph_operation="build")
    parser.add_argument("--revision", required=True, help="Exact current repository commit")
    parser.add_argument("--operation", required=True, help="Stable operation UUID for recovery")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--expected", help="Previous native graph revision UUID")
    group.add_argument("--initial", action="store_true", help="Require an empty extension scope")


def query(parser: argparse.ArgumentParser) -> None:
    """
    Declare evidence retrieval and existing context budgets.

    Args:
        parser (argparse.ArgumentParser): Query leaf.

    Returns:
        None: Query options are registered without side effects.
    """
    common(parser)
    parser.set_defaults(graph_operation="query")
    parser.add_argument("--revision", required=True, help="Exact current repository commit")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--direction", choices=("symbol", "callers", "impact"), default="symbol")
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--nodes", type=int, default=40)
    parser.add_argument("--edges", type=int, default=100)
    parser.add_argument("--tokens", type=int, default=8000, help="Conservative UTF-8 byte token bound")
    parser.add_argument("--bytes", type=int, default=16000)
    parser.add_argument("--elapsed-ms", type=int, default=10000)


def recover(parser: argparse.ArgumentParser) -> None:
    """
    Declare explicit recovery of an uncertain graph publication.

    Args:
        parser (argparse.ArgumentParser): Recovery leaf.

    Returns:
        None: Only the existing client and protected output are selected.
    """
    common(parser)
    parser.set_defaults(graph_operation="recover")


def rotate(parser: argparse.ArgumentParser) -> None:
    """
    Select a separately approved native key-generation rotation.

    Args:
        parser (argparse.ArgumentParser): Rotation leaf.

    Returns:
        None: The command uses configured generations without creating keys.
    """
    common(parser)
    parser.set_defaults(graph_operation="rotate")
    parser.add_argument("--operation", required=True)
    parser.add_argument("--mode", choices=("rewrap", "reseal", "resign"), required=True)


def command() -> Command:
    """
    Compose graph leaves through the shared recursive CLI builder.

    Returns:
        Command: Optional graph command subtree.
    """
    return Command(
        "codegraph",
        "Build and query encrypted repository evidence",
        children=(
            Command("setup", "Prepare optional 1Password broker custody", setup, "witful.codegraph.setup.cli"),
            Command("build", "Publish an encrypted generation", build, "witful.codegraph.cli"),
            Command("query", "Retrieve bounded source references", query, "witful.codegraph.cli"),
            Command("recover", "Reconcile an uncertain publication", recover, "witful.codegraph.cli"),
            Command("rotate", "Rotate approved key generations", rotate, "witful.codegraph.cli"),
        ),
    )
