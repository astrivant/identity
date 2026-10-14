"""
Compose reusable command trees and dispatch one parsed namespace to its selected runtime.
"""

from __future__ import annotations

import argparse
from importlib import import_module
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from attrs import frozen

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["Command", "dispatch"]


@runtime_checkable
class Executable(Protocol):
    """
    Describe a lazily imported command module.
    """

    def execute(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
        """
        Execute validated arguments without parsing them again.

        Args:
            args (argparse.Namespace): Selected command arguments.
            parser (argparse.ArgumentParser): Owning parser for actionable errors.

        Returns:
            int: Operation status.
        """
        ...


@frozen
class Command:
    """
    Describe a command group or executable leaf independently of its position in a tree.

    Attributes:
        name (str): Public command name.
        description (str): Help text for this node.
        configure (Callable[[argparse.ArgumentParser], object] | None): Optional local argument declarations.
        module (str | None): Leaf runtime module implementing execute.
        children (tuple[Command, ...]): Child nodes composed through the same contract.
        aliases (tuple[str, ...]): Alternate names at this node's parent.
        destination (str): Namespace field for child selection; suppressed unless a runtime needs it.
    """

    name: str
    description: str
    configure: Callable[[argparse.ArgumentParser], object] | None = None
    module: str | None = None
    children: tuple[Command, ...] = ()
    aliases: tuple[str, ...] = ()
    destination: str = argparse.SUPPRESS

    def __attrs_post_init__(self) -> None:
        """
        Reject nodes whose execution ownership is missing or ambiguous.

        Returns:
            None: This node is either a group or an executable leaf.

        Raises:
            ValueError: Both children and a runtime, or neither, were supplied.
        """
        if bool(self.children) == bool(self.module):
            raise ValueError("Command requires either children or a runtime module")

    def register(self, commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        """
        Attach a fresh parser and all descendants to a parent group.

        Args:
            commands (argparse._SubParsersAction[argparse.ArgumentParser]): Parent-owned subparser collection.

        Returns:
            None: Arguments and dispatch metadata are registered without importing runtime code.
        """
        parser = commands.add_parser(self.name, aliases=list(self.aliases), help=self.description, description=self.description)
        self.populate(parser)

    def populate(self, parser: argparse.ArgumentParser) -> None:
        """
        Apply this node to a standalone or parent-owned parser recursively.

        Args:
            parser (argparse.ArgumentParser): Fresh parser owned by this node.

        Returns:
            None: Required children or the selected leaf handler are registered.
        """
        if self.configure is not None:
            self.configure(parser)

        # Branches require an explicit child; they never silently execute an ancestor's handler.
        if self.children:
            commands = parser.add_subparsers(dest=self.destination, required=True)
            for child in self.children:
                child.register(commands)
        else:
            parser.set_defaults(handler=self, command_parser=parser)

    def invoke(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
        """
        Load only the selected leaf's runtime and preserve its status and errors.

        Args:
            args (argparse.Namespace): Namespace parsed once by the entrypoint.
            parser (argparse.ArgumentParser): Selected leaf parser for errors.

        Returns:
            int: Runtime operation status.

        Raises:
            TypeError: A group was invoked or its runtime lacks the execute contract.
        """
        if self.module is None:
            raise TypeError("Command groups cannot be invoked")
        module: object = import_module(self.module)
        if not isinstance(module, Executable):
            raise TypeError("Command module does not implement execute")
        return module.execute(args, parser)


def dispatch(args: argparse.Namespace) -> int:
    """
    Invoke the selected leaf from one already parsed command tree.

    Args:
        args (argparse.Namespace): Parsed namespace carrying leaf-owned dispatch metadata.

    Returns:
        int: Selected runtime status.

    Raises:
        TypeError: Parser registration omitted or replaced the typed dispatch metadata.
    """
    handler: object = getattr(args, "handler", None)
    parser: object = getattr(args, "command_parser", None)
    if not isinstance(handler, Command) or not isinstance(parser, argparse.ArgumentParser):
        raise TypeError("Command registration is incomplete")
    return handler.invoke(args, parser)
