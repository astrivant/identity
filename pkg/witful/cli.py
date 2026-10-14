"""
Compose one argparse command hierarchy while loading runtime services only for the selected domain.
"""

from __future__ import annotations

import argparse
from importlib import import_module
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from attrs import frozen

from witful.commands import (
    awareness,
    checkpoints,
    collection,
    completion,
    context,
    delivery,
    instances,
    knowledge,
    life,
    privacy,
    reflection,
    registry,
    repertoire,
    sleeves,
    storage,
)
from witful.commands.project import configure as project

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = ["build_parser", "main"]


@runtime_checkable
class Executable(Protocol):
    """
    Describe a lazily imported domain command module.
    """

    def execute(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
        """
        Dispatch an already validated namespace without parsing again.

        Args:
            args (argparse.Namespace): Selected domain arguments.
            parser (argparse.ArgumentParser): Owning parser for actionable errors.

        Returns:
            int: Operation status.
        """
        ...


@frozen
class Command:
    """
    Assemble a command from lightweight argument declarations and its runtime module.

    Attributes:
        name (str): Public subcommand name.
        description (str): Root help description.
        configure (Callable[[argparse.ArgumentParser], object]): Parser composition function.
        module (str): Runtime module implementing the typed execute contract.
    """

    name: str
    description: str
    configure: Callable[[argparse.ArgumentParser], object]
    module: str

    def register(self, commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        """
        Add this command and its selected handler to a parent group.

        Args:
            commands (argparse._SubParsersAction[argparse.ArgumentParser]): Parent-owned subparser collection.

        Returns:
            None: Parser and handler are registered; runtime code remains unloaded.
        """
        parser = commands.add_parser(self.name, help=self.description, description=self.description)
        self.configure(parser)
        parser.set_defaults(handler=self, command_parser=parser)

    def invoke(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
        """
        Load and execute only the selected command module.

        Args:
            args (argparse.Namespace): Namespace parsed once by the root.
            parser (argparse.ArgumentParser): Selected parser for domain errors.

        Returns:
            int: Domain status without altering its error semantics.
        """
        module: object = import_module(self.module)
        if not isinstance(module, Executable):
            raise TypeError("Command module does not implement execute")
        return module.execute(args, parser)


def build_parser() -> argparse.ArgumentParser:
    """
    Build the complete public hierarchy with existing top-level knowledge commands.

    Returns:
        argparse.ArgumentParser: Root parser with domain-owned subparsers and handlers.
    """
    parser = argparse.ArgumentParser(description="Manage reviewed knowledge, evidence and delivery workflows")
    commands = knowledge.configure(parser)
    parser.set_defaults(
        handler=Command("knowledge", "Knowledge operations", knowledge.configure, "witful.knowledge.cli"), command_parser=parser
    )
    for command in (
        Command("init", "Initialize a collection", project, "witful.project"),
        Command("lessons", "Search and record sourced lessons", storage.configure, "witful.storage.cli"),
        Command("life", "Record and replay decisions", life.configure, "witful.life.cli"),
        Command("repertoire", "Curate observed tools and problems", repertoire.configure, "witful.repertoire.cli"),
        Command("checkpoints", "Track project chapters", checkpoints.configure, "witful.checkpoints.cli"),
        Command("reflection", "Review decisions against current evidence", reflection.configure, "witful.reflection.cli"),
        Command("awareness", "Publish selected figures", awareness.configure, "witful.awareness.cli"),
        Command("collection", "Manage protected collections", collection.configure, "witful.collection.cli"),
        Command("privacy", "Scan publication inputs", privacy.configure, "witful.privacy.cli"),
        Command("registry", "Inspect Python package names", registry.configure, "witful.registry.names"),
        Command("instances", "Record runtime provenance", instances.configure, "witful.instances.cli"),
        Command("sleeve", "Isolate concurrent work", sleeves.configure, "witful.sleeves.cli"),
        Command("completion", "Review completion coverage", completion.configure, "witful.completion.cli"),
        Command("context", "Resolve advisory working context", context.configure, "witful.context.cli"),
        Command("delivery", "Review and prepare PRs and MRs", delivery.configure, "witful.delivery.cli"),
    ):
        command.register(commands)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """
    Parse the command hierarchy once and invoke the selected domain handler.

    Args:
        argv (Sequence[str] | None): Explicit arguments, or the current process command line.

    Returns:
        int: Selected domain status; argparse handles help and invalid syntax.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    handler: object = args.handler
    selected_parser: object = args.command_parser
    if not isinstance(handler, Command) or not isinstance(selected_parser, argparse.ArgumentParser):
        raise TypeError("Command registration is incomplete")
    return handler.invoke(args, selected_parser)
