"""
Compose recursively reusable native controller, record, ref and recovery command groups.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from witful.commands.builder import Command

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable


def options(operation: str) -> Callable[[argparse.ArgumentParser], None]:
    """
    Bind a leaf's arguments without inspecting argv or importing runtime services.

    Args:
        operation (str): Internal native leaf operation.

    Returns:
        Callable[[argparse.ArgumentParser], None]: Reusable parser configurator.
    """

    def configure(parser: argparse.ArgumentParser) -> None:
        """
        Register the selected leaf's typed input and output boundaries.

        Args:
            parser (argparse.ArgumentParser): Parent-owned parser.

        Returns:
            None: Arguments and dispatch metadata are registered once.
        """
        parser.set_defaults(native_operation=operation)
        if operation == "schema":
            parser.add_argument("--kind", choices=("server", "client", "evidence"), default="server")
            return
        if operation in {"serve", "check", "health"}:
            parser.add_argument("--config", type=Path, required=True)
            return
        parser.add_argument("--client", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=operation in {"read", "history"})
        if operation in {"append", "branch"}:
            parser.add_argument("--operation", required=True, help="Stable operation UUID; reuse unchanged after an unknown outcome")
        if operation in {"append", "history", "search"}:
            parser.add_argument("--ref", default="main")
        if operation == "append":
            parser.add_argument("--expected", help="Exact current logical head; omit only to create an absent branch")
            parser.add_argument("--input", type=Path, required=True, help="Explicit protected JSON import array of domain/value records")
        if operation == "branch":
            parser.add_argument("--name", required=True)
            parser.add_argument("--immutable", action="store_true")
        if operation in {"read", "branch"}:
            parser.add_argument("--record", required=True)
        if operation == "search":
            parser.add_argument("--query", required=True)

    return configure


def leaf(name: str, description: str, operation: str) -> Command:
    """
    Reuse the selected runtime handler within any level of the command hierarchy.

    Args:
        name (str): Public subcommand name.
        description (str): User-facing purpose.
        operation (str): Internal operation identifier.

    Returns:
        Command: Fully configured leaf with lazy runtime dispatch.
    """
    return Command(name, description, options(operation), "witful.native.cli")


def command() -> Command:
    """
    Define the native command tree independently of its parent parser.

    Returns:
        Command: Recursive controller, record, ref, recovery and schema operations.
    """
    return Command(
        "native",
        "Operate protected native identity storage",
        children=(
            Command(
                "controller",
                "Manage the authenticated native runtime",
                children=(
                    leaf("serve", "Serve the consolidated TLS application", "serve"),
                    leaf("check", "Validate configuration and current protection evidence", "check"),
                    leaf("health", "Probe this local controller over authenticated TLS", "health"),
                ),
            ),
            Command(
                "record",
                "Access individually typed native records",
                children=(
                    leaf("append", "Append a validated batch under an expected branch head", "append"),
                    leaf("read", "Read an exact revision into protected storage", "read"),
                    leaf("history", "Export a selected causal view into protected storage", "history"),
                    leaf("search", "Search authorized memory without persistent plaintext indexes", "search"),
                ),
            ),
            Command(
                "ref",
                "Manage native branch and retained tag refs",
                children=(leaf("create", "Create a branch or immutable tag only when absent", "branch"),),
            ),
            Command(
                "recovery",
                "Reconcile uncertain durable operations",
                children=(leaf("reconcile", "Resolve an exact pending prepared transaction", "recover"),),
            ),
            leaf("schema", "Print a closed native configuration contract", "schema"),
        ),
    )
