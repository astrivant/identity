"""
Define closed provenance for independently scoped reviewed adoption without granting source traversal.
"""

from __future__ import annotations

from typing import Literal

from attrs import frozen

from witful.exceptions import NativeError
from witful.native.models import Adoption, Pointer, parse
from witful.native.storage import Scope  # noqa: TC001 - nested cattrs/schema model resolved at runtime.


@frozen
class ChildEvidence:
    """
    Disclose only selected source identifiers and exact reviewed source state to one independently authorized child.

    Attributes:
        source_scope (Scope): Opaque parent scope; this reference grants no access.
        source (Pointer): Pinned reviewed parent frontier.
        adopted (tuple[Adoption, ...]): Selected source-to-new child revision mappings.
        reviewer (str): Authenticated review certificate fingerprint.
        reason (str): Explicit reviewed disclosure rationale.
        recorded (str): Actual adoption time, independent of original domain times.
        role (Literal["child"]): Closed child-provenance discriminator.
        version (Literal[1]): Provenance schema version.
    """

    source_scope: Scope
    source: Pointer
    adopted: tuple[Adoption, ...]
    reviewer: str
    reason: str
    recorded: str
    role: Literal["child"] = "child"
    version: Literal[1] = 1


@frozen
class Output:
    """
    Retain one complete reviewed output mapping only inside the parent's encrypted decision.

    Attributes:
        scope (Scope): Independently provisioned child scope.
        backend (str): Configured child storage UUID.
        root (Pointer): Exact child frontier published by the group.
        ref (str): New child branch name, encrypted at rest.
        adopted (tuple[Adoption, ...]): Exact source-to-child revision mappings.
    """

    scope: Scope
    backend: str
    root: Pointer
    ref: str
    adopted: tuple[Adoption, ...]


@frozen
class Decision:
    """
    Preserve the complete fork/split review and omissions in the parent without disclosing sibling selections to children.

    Attributes:
        mode (Literal["fork", "split"]): One independently scoped child or several atomic outputs.
        source (Pointer): Pinned reviewed parent frontier.
        outputs (tuple[Output, ...]): Complete reviewed output mappings.
        omitted (tuple[str, ...]): Parent revisions excluded from every child; retained only with the parent's authority.
        reason (str): Explicit review rationale.
        reviewer (str): Authenticated reviewer certificate fingerprint.
        recorded (str): Actual group adoption time.
        role (Literal["parent"]): Closed parent-decision discriminator.
        version (Literal[1]): Decision schema version.
    """

    mode: Literal["fork", "split"]
    source: Pointer
    outputs: tuple[Output, ...]
    omitted: tuple[str, ...]
    reason: str
    reviewer: str
    recorded: str
    role: Literal["parent"] = "parent"
    version: Literal[1] = 1


def validate(value: object) -> None:
    """
    Require closed typed derivation evidence during complete-history backup and recipient recovery.

    Args:
        value (object): Decrypted authenticated record, still requiring domain-shape validation.

    Returns:
        None: The retained record matches its explicit parent or child schema.
    """
    if not isinstance(value, dict):
        raise NativeError("invalid")
    if value.get("role") == "child":
        parsed = parse(value, ChildEvidence)
        if not parsed.adopted or not parsed.reason.strip():
            raise NativeError("invalid")
    else:
        decision = parse(value, Decision)
        if not decision.outputs or not decision.reason.strip() or (decision.mode == "fork") != (len(decision.outputs) == 1):
            raise NativeError("invalid")
        if len({output.scope for output in decision.outputs}) != len(decision.outputs):
            raise NativeError("invalid")
