"""
Describe a reusable toolbox, problem taxonomy, and sourced observations of their use.
"""

from __future__ import annotations

from typing import Literal

from attrs import frozen

__all__ = ["Inventory", "Problem", "Tool", "Use"]


@frozen
class Tool:
    """
    Identify a tool independently of whether it has been used in a recorded task.

    Attributes:
        id (str): Stable lookup identifier.
        name (str): Display name.
        kind (Literal["package", "service", "command", "script"]): Tool category.
        purpose (str): Concise problem-solving capability.
        reference (str): Authoritative source or maintained local entry point.
    """

    id: str
    name: str
    kind: Literal["package", "service", "command", "script"]
    purpose: str
    reference: str


@frozen
class Problem:
    """
    Connect a concrete problem category to its broader conceptual parent.

    Attributes:
        id (str): Stable classification identifier.
        name (str): Human-readable problem type.
        parent (str | None): Broader problem ID; None denotes an abstract root.
    """

    id: str
    name: str
    parent: str | None = None


# docref:1 repertoire.inventory -> docs/intent-graphs.md
@frozen
class Inventory:
    """
    Own reviewed toolbox definitions and problem categories without manufacturing use counts.

    Attributes:
        tools (tuple[Tool, ...]): Unique reusable tools, including unused catalog entries.
        problems (tuple[Problem, ...]): Acyclic problem hierarchy of arbitrary useful depth.
        version (Literal[1]): Supported source format.
    """

    tools: tuple[Tool, ...] = ()
    problems: tuple[Problem, ...] = ()
    version: Literal[1] = 1


@frozen
class Use:
    """
    Record one complete, sourced task observation without counting mere tool mentions.

    Attributes:
        id (str): Content-derived observation identifier.
        task (str): Stable task reference; later observations revise this task's current counts.
        tools (tuple[str, ...]): Sorted unique tool IDs actually used.
        problems (tuple[str, ...]): Sorted unique directly addressed problem IDs.
        concepts (tuple[str, ...]): Sorted concept IDs from the knowledge hierarchy, if relevant.
        evidence (str): Actual outcome or verification supporting the observation.
        observed_at (str): Time of recording with timezone, not an inferred historical timestamp.
    """

    id: str
    task: str
    tools: tuple[str, ...]
    problems: tuple[str, ...]
    concepts: tuple[str, ...]
    evidence: str
    observed_at: str
