"""
Keep optional graph command composition and plaintext output ownership explicit.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from witful.cli import build_parser
from witful.codegraph.cli import require_pipe
from witful.exceptions import NativeError

if TYPE_CHECKING:
    from pathlib import Path


def test_output_requires_memory_pipe(tmp_path: Path) -> None:
    """
    Refuse durable plaintext redirects while allowing a separately reviewed pipe consumer.

    Args:
        tmp_path (Path): Disposable output fixture.

    Returns:
        None: A regular file cannot be used as the graph result sink.
    """
    with (tmp_path / "output").open("wb") as output:
        with pytest.raises(NativeError, match="denied"):
            require_pipe(output.fileno())
    reader, writer = os.pipe()
    try:
        require_pipe(writer)
    finally:
        os.close(reader)
        os.close(writer)


def test_recursive_graph_leaves_preserve_arguments() -> None:
    """
    Parse build, query and recovery through the common hierarchy without manual argv routing.

    Returns:
        None: Each selected leaf owns its arguments and runtime dispatch.
    """
    parser = build_parser()
    common = ["--client", "/protected/client.json", "--pipe"]
    build = parser.parse_args(["codegraph", "build", *common, "--revision", "a" * 40, "--operation", "operation", "--initial"])
    assert build.graph_operation == "build" and build.expected is None
    query = parser.parse_args(["codegraph", "query", *common, "--revision", "a" * 40, "--symbol", "leaf", "--tokens", "100"])
    assert query.graph_operation == "query" and query.tokens == 100
    assert parser.parse_args(["codegraph", "recover", *common]).graph_operation == "recover"
    with pytest.raises(SystemExit):
        parser.parse_args(["codegraph", "query", "--client", "/protected/client.json", "--revision", "a" * 40, "--symbol", "leaf"])
