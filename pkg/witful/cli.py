"""
Compose one argparse command hierarchy while loading runtime services only for the selected domain.
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from witful.commands import (
    checkpoints,
    codegraph,
    collection,
    completion,
    context,
    delivery,
    instances,
    knowledge,
    life,
    native,
    privacy,
    reflection,
    registry,
    repertoire,
    representation,
    sleeves,
    storage,
)
from witful.commands.builder import Command, dispatch
from witful.commands.project import configure as project

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["build_parser", "main"]


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
        Command("awareness", "Publish professional representation figures", representation.configure, "witful.representation.cli"),
        Command("collection", "Manage protected collections", collection.configure, "witful.collection.cli"),
        Command("privacy", "Scan publication inputs", privacy.configure, "witful.privacy.cli"),
        Command("registry", "Inspect Python package names", registry.configure, "witful.registry.names"),
        Command("instances", "Record runtime provenance", instances.configure, "witful.instances.cli"),
        Command("sleeve", "Isolate concurrent work", sleeves.configure, "witful.sleeves.cli"),
        Command("completion", "Review completion coverage", completion.configure, "witful.completion.cli"),
        Command("context", "Resolve advisory working context", context.configure, "witful.context.cli"),
        codegraph.command(),
        delivery.command(),
        native.command(),
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
    return dispatch(parser.parse_args(argv))
