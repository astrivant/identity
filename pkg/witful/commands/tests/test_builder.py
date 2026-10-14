"""
Verify recursive composition, option ownership and lazy leaf dispatch across command depths.
"""

from __future__ import annotations

import argparse
from types import ModuleType
from typing import TYPE_CHECKING

import pytest
from witful.commands import builder
from witful.commands.builder import Command, dispatch

if TYPE_CHECKING:
    from pytest import CaptureFixture, MonkeyPatch


def _options(parser: argparse.ArgumentParser) -> None:
    """
    Declare parent options whose values must survive nested parsing.

    Args:
        parser (argparse.ArgumentParser): Parent parser.

    Returns:
        None: Account selection is registered once.
    """
    parser.add_argument("--account", default="default")


def _value(parser: argparse.ArgumentParser) -> None:
    """
    Declare a typed leaf input.

    Args:
        parser (argparse.ArgumentParser): Leaf parser.

    Returns:
        None: A required integer value is registered.
    """
    parser.add_argument("--value", type=int, required=True)


def _tree(depth: int) -> tuple[Command, list[str]]:
    """
    Build a reusable synthetic tree with the same contract at every tier.

    Args:
        depth (int): Number of command groups above the selected leaf.

    Returns:
        tuple[Command, list[str]]: Tree and canonical command path beneath its root.
    """
    node = Command("run", "Run a selected operation", _value, "synthetic.selected", aliases=("go",))
    path = ["run"]
    for index in range(depth):
        name = f"tier{index}"
        node = Command(name, "Select a child", children=(node, Command("unused", "Other operation", module="synthetic.unused")))
        path.insert(0, name)
    return Command("root", "Select account and operation", _options, children=(node,)), path


@pytest.mark.parametrize("depth", [0, 2, 5])
def test_recursive_dispatch_preserves_parent_inputs_and_leaf_ownership(depth: int, monkeypatch: MonkeyPatch) -> None:
    """
    Select only the deepest runtime while retaining ancestor options and parser ownership.

    Args:
        depth (int): Nested group count to exercise without a configured depth ceiling.
        monkeypatch (MonkeyPatch): Isolate runtime loading from real providers.

    Returns:
        None: Exactly one selected runtime receives the complete typed namespace and leaf parser.
    """
    loaded: list[str] = []

    class Runtime(ModuleType):
        """
        Provide an explicitly typed synthetic lazy runtime.
        """

        def execute(self, args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
            """
            Verify the runtime sees leaf and ancestor inputs.

            Args:
                args (argparse.Namespace): Parsed tree inputs.
                parser (argparse.ArgumentParser): Selected leaf parser.

            Returns:
                int: Distinct status proving dispatch preserves the handler outcome.
            """
            assert args.account == "review"
            assert args.value == 17
            assert parser.prog.endswith(" run")
            return 23

    def load(name: str) -> ModuleType:
        """
        Capture the selected import without loading any real runtime.

        Args:
            name (str): Requested module.

        Returns:
            ModuleType: Synthetic executable module.
        """
        loaded.append(name)
        return Runtime(name)

    monkeypatch.setattr(builder, "import_module", load)
    tree, path = _tree(depth)
    parser = argparse.ArgumentParser(prog="example")
    tree.populate(parser)
    assert loaded == []
    args = parser.parse_args(["--account", "review", *path[:-1], "go", "--value", "17"])
    assert loaded == []
    assert dispatch(args) == 23
    assert loaded == ["synthetic.selected"]


def test_same_tree_can_be_mounted_more_than_once() -> None:
    """
    Reuse immutable declarations without sharing parser defaults or selected arguments.

    Returns:
        None: Two parent positions retain distinct parsers and option values.
    """
    tree, path = _tree(2)
    first = argparse.ArgumentParser(prog="standalone")
    second = argparse.ArgumentParser(prog="application")
    tree.populate(first)
    tree.register(second.add_subparsers(required=True))
    left = first.parse_args(["--account", "first", *path, "--value", "1"])
    right = second.parse_args(["root", "--account", "second", *path, "--value", "2"])
    assert (left.account, left.value) == ("first", 1)
    assert (right.account, right.value) == ("second", 2)
    assert left.command_parser is not right.command_parser
    assert left.command_parser.prog.startswith("standalone ")
    assert right.command_parser.prog.startswith("application root ")


@pytest.mark.parametrize("prefix", [[], ["tier1"], ["tier1", "tier0"], ["tier1", "tier0", "go"]])
def test_each_tier_handles_help_and_missing_inputs_without_runtime_imports(
    prefix: list[str], monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    """
    Keep help and input failures inside argparse at every level.

    Args:
        prefix (list[str]): Root, intermediate group or aliased leaf selection.
        monkeypatch (MonkeyPatch): Reject any runtime loading before dispatch.
        capsys (CaptureFixture[str]): Capture argparse help and diagnostics.

    Returns:
        None: Help succeeds and missing/invalid input fails before executing any runtime.
    """

    def unexpected_import(name: str) -> ModuleType:
        """
        Fail if parser-only behavior tries loading a runtime.

        Args:
            name (str): Unexpected runtime module.

        Returns:
            ModuleType: Never returned.

        Raises:
            AssertionError: Runtime imports are outside parser construction and help.
        """
        raise AssertionError(name)

    monkeypatch.setattr(builder, "import_module", unexpected_import)
    tree, _ = _tree(2)
    parser = argparse.ArgumentParser(prog="example")
    tree.populate(parser)
    with pytest.raises(SystemExit) as result:
        parser.parse_args([*prefix, "--help"])
    assert result.value.code == 0
    assert "usage:" in capsys.readouterr().out
    for arguments in (prefix, [*prefix, "--invalid"]):
        with pytest.raises(SystemExit) as result:
            parser.parse_args(arguments)
        assert result.value.code == 2
        assert "error:" in capsys.readouterr().err


def test_ambiguous_and_incomplete_node_definitions_fail() -> None:
    """
    Reject missing execution ownership before the tree reaches an entrypoint.

    Returns:
        None: Empty and mixed nodes cannot become executable commands accidentally.
    """
    leaf = Command("leaf", "Execute", module="synthetic.selected")
    with pytest.raises(ValueError, match="either children or a runtime"):
        Command("empty", "No implementation")
    with pytest.raises(ValueError, match="either children or a runtime"):
        Command("mixed", "Ambiguous ownership", module="synthetic.selected", children=(leaf,))
    with pytest.raises(TypeError, match="registration is incomplete"):
        dispatch(argparse.Namespace())
