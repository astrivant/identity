"""
Adapt the released broker SDK without giving storage adapters key material or transport ownership.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from agent_broker_sdk.exceptions import BrokerError
from agent_broker_sdk.models import Binding, Request
from attrs import field, frozen

from witful.exceptions import NativeError
from witful.native.context import identifier

if TYPE_CHECKING:
    from agent_broker_sdk.client import CryptoClient

    from witful.native.context import Context

__all__ = ["BrokerKeys"]


@frozen
class BrokerKeys:
    """
    Bind each independent key request to the service's current authorized access revision.

    Attributes:
        client (CryptoClient): Maintained certificate-authenticated SDK, owned by the caller.
        grant (str): Operator-issued key grant UUID.
        task (str): Admitted task UUID.
        authority (str): Current authority UUID, independent of immutable record context.
        policy (str): Current key-policy UUID.
    """

    client: CryptoClient = field(repr=False)
    grant: str
    task: str
    authority: str
    policy: str

    def __attrs_post_init__(self) -> None:
        """
        Reject malformed access bindings before the first provider operation.

        Returns:
            None: Every access identifier belongs to the closed broker contract.
        """
        for value in (self.grant, self.task, self.authority, self.policy):
            identifier(value)

    def invoke(self, action: Literal["wrap", "unwrap", "sign"], generation: str, context: Context, payload: bytes) -> bytes:
        """
        Make one bounded SDK request; ambiguous outcomes never trigger implicit retries.

        Args:
            action (Literal["wrap", "unwrap", "sign"]): Independently authorized cryptographic purpose.
            generation (str): Approved key-generation UUID.
            context (Context): Expected immutable identity and record binding.
            payload (bytes): Transient key material or ciphertext digest, excluded from diagnostics.

        Returns:
            bytes: Transient service response, never persisted by this adapter.

        Raises:
            NativeError: Broker authorization or transport failed without exposing its diagnostic input.
        """
        identifier(generation)
        binding = Binding(
            context.tenant, context.identity, context.record, context.kind, context.schema, context.codec, context.hash, context.envelope
        )
        request = Request(
            str(uuid4()),
            self.grant,
            action,
            generation,
            binding,
            self.task,
            self.authority,
            self.policy,
            base64.b64encode(payload).decode("ascii"),
        )
        try:
            return self.client.invoke(request)
        except BrokerError:
            raise NativeError("unavailable") from None
