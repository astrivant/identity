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
            parser.add_argument("--kind", choices=("server", "client", "evidence", "recipient"), default="server")
            return
        if operation in {"serve", "check", "health"}:
            parser.add_argument("--config", type=Path, required=True)
            return
        parser.add_argument("--client", type=Path, required=True)
        parser.add_argument(
            "--output", type=Path, required=operation in {"read", "history", "export", "share", "original-list", "original-restore"}
        )
        if operation in {"append", "branch", "merge", "rotate", "migrate", "migration-abort", "original-capture", "fork", "split"}:
            parser.add_argument("--operation", required=True, help="Stable operation UUID; reuse unchanged after an unknown outcome")
        if operation in {"append", "history", "search"}:
            parser.add_argument("--ref", default="main")
        if operation == "append":
            parser.add_argument("--expected", help="Exact current logical head; omit only to create an absent branch")
            parser.add_argument("--input", type=Path, required=True, help="Explicit protected JSON import array of domain/value records")
        if operation in {"fork", "split"}:
            parser.add_argument("--expected", required=True, help="Exact reviewed parent frontier UUID")
            parser.add_argument(
                "--input", type=Path, required=True, help="Protected review document with reason and selected child outputs"
            )
        if operation == "merge":
            parser.add_argument("--target", required=True)
            parser.add_argument("--candidate", required=True)
            parser.add_argument("--expected", required=True, help="Exact reviewed target logical head")
            parser.add_argument("--reviewed", required=True, help="Exact reviewed candidate logical head")
            parser.add_argument("--input", type=Path, required=True, help="Protected review document containing reason and selections")
        if operation in {"migrate", "restore"}:
            parser.add_argument("--destination", required=True, help="Explicit configured inactive backend UUID")
        if operation == "restore":
            parser.add_argument("--input", type=Path, required=True, help="Signed encrypted binary export")
        if operation == "share":
            parser.add_argument("--recipient", help="Configured identity-bound public recipient alias; omitted uses current custody")
        if operation == "rotate":
            parser.add_argument("--mode", choices=("rewrap", "reseal", "resign"), required=True)
        if operation == "branch":
            parser.add_argument("--name", required=True)
            parser.add_argument("--immutable", action="store_true")
        if operation in {"read", "branch"}:
            parser.add_argument("--record", required=True)
        if operation in {"original-capture", "original-restore"}:
            parser.add_argument("--path", required=True, help="Identity-bound operator-configured source or destination alias")
        if operation == "original-capture":
            parser.add_argument("--unreachable", action="store_true", help="Explicitly retain available unreachable original objects")
            parser.add_argument("--reflogs", action="store_true", help="Explicitly retain available reflogs; requires --unreachable")
        if operation == "original-restore":
            parser.add_argument("--record", required=True, help="Exact original archive UUID from original list")
        if operation == "search":
            parser.add_argument("--query", required=True)

    return configure


def disclosure_options(parser: argparse.ArgumentParser) -> None:
    """
    Configure offline recipient verification without requesting a controller connection or source credentials.

    Args:
        parser (argparse.ArgumentParser): Parent-owned leaf parser.

    Returns:
        None: Only explicit file paths are accepted; secret values never appear as command arguments.
    """
    parser.add_argument("--input", type=Path, required=True, help="Signed encrypted native sharing package")
    parser.add_argument("--trust", type=Path, required=True, help="Independently supplied context, frontier and sender public-key pins")
    parser.add_argument("--private-key", type=Path, required=True, help="Protected encrypted recipient RSA PEM")
    parser.add_argument("--password-file", type=Path, required=True, help="Protected owner-only file containing the exact PEM password")
    parser.add_argument("--output", type=Path, required=True, help="New protected JSON file; exact original source bytes use base64")


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
                children=(
                    leaf("create", "Create a branch or immutable tag only when absent", "branch"),
                    leaf("fork", "Publish one independently scoped reviewed adoption", "fork"),
                    leaf("split", "Publish multiple independently scoped reviewed adoptions atomically", "split"),
                    leaf("merge", "Apply explicit reviewed adoptions while retaining both histories", "merge"),
                ),
            ),
            Command(
                "recovery",
                "Reconcile uncertain durable operations",
                children=(
                    leaf("reconcile", "Resolve an exact pending prepared transaction", "recover"),
                    leaf("export", "Write a signed encrypted complete-history recovery package", "export"),
                    leaf("share", "Write a sender-signed export recoverable with only the recipient key", "share"),
                    Command(
                        "inspect",
                        "Verify a recipient export offline into protected storage",
                        disclosure_options,
                        "witful.native.sharing_cli",
                    ),
                    leaf("restore", "Restore into an inactive configured backend without cutover", "restore"),
                ),
            ),
            Command(
                "original",
                "Preserve and recover exact original Git repositories",
                children=(
                    leaf("capture", "Capture an explicitly configured original Git directory", "original-capture"),
                    leaf("list", "List complete archive inventories into protected storage", "original-list"),
                    leaf("share", "Write a sender-signed export recoverable with only the recipient key", "share"),
                    Command(
                        "inspect",
                        "Verify a recipient export offline into protected storage",
                        disclosure_options,
                        "witful.native.sharing_cli",
                    ),
                    leaf("restore", "Restore into a configured absent protected path", "original-restore"),
                ),
            ),
            Command(
                "migration",
                "Move exact history through a fenced routing-epoch transition",
                children=(
                    leaf("run", "Migrate or reverse-migrate without discarding new destination writes", "migrate"),
                    leaf("abort", "Unfreeze only before a cutover candidate is prepared", "migration-abort"),
                ),
            ),
            Command(
                "key",
                "Manage current representations without retiring history keys",
                children=(leaf("rotate", "Rewrap, reseal or replace signatures using configured custody", "rotate"),),
            ),
            leaf("schema", "Print a closed native configuration contract", "schema"),
        ),
    )
