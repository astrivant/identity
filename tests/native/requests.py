"""
Build synthetic native wire requests shared by API contract tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from witful.native import codec

if TYPE_CHECKING:
    from tests.native.runtime import Runtime


def body(runtime: Runtime, arguments: object) -> bytes:
    """
    Encode the public request contract without allowing a caller to choose its authenticated certificate identity.

    Args:
        runtime (Runtime): Synthetic service grant.
        arguments (object): Operation-owned closed argument map.

    Returns:
        bytes: Native CBOR request.
    """
    access = runtime.access
    return codec.encode(
        {
            "access": {
                "tenant": access.scope.tenant,
                "identity": access.scope.identity,
                "grant": access.grant,
                "task": access.task,
                "epoch": access.epoch,
                "policy": access.policy,
            },
            "arguments": arguments,
        }
    )
