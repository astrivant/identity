"""
Configure explicitly authorized synthetic projection targets shared by native delivery contract tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from uuid import uuid4

import psycopg
from attrs import evolve, frozen
from cryptography.hazmat.primitives.asymmetric import rsa
from witful.exceptions import NativeError
from witful.native.projection.models import Policy, Target

from tests.native.conftest import Keys

if TYPE_CHECKING:
    from witful.native.context import Context
    from witful.native.envelope import KeyService
    from witful.native.service import Service

    from tests.native.database import Databases
    from tests.native.runtime import Runtime


def configured(runtime: Runtime, databases: Databases) -> Service:
    """
    Explicitly approve synthetic projection and one scoped destination while keeping every network call outside the test.

    Args:
        runtime (Runtime): Current actual source backend.
        databases (Databases): Disposable independent policy administrator.

    Returns:
        Service: Projection-enabled test service with a separately configured transport grant reference.
    """
    with psycopg.connect(databases.authority_admin) as admin:
        admin.execute("UPDATE witful_native_grants SET actions=array_append(actions, 'project') WHERE id=%s", (runtime.access.grant,))
    target = Target(
        str(uuid4()),
        runtime.access.scope.tenant,
        runtime.access.scope.identity,
        "https://gateway.invalid",
        "fixture-ca",
        "fixture-cert",
        "fixture-key",
        str(uuid4()),
        str(uuid4()),
    )
    wrapping = str(uuid4())
    custody = runtime.service.keys(runtime.access).keys
    assert isinstance(custody, Keys)
    custody.wrapping[wrapping] = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    return evolve(runtime.service, projection=Policy(mode="required", targets=(target,), permit_wrapping=wrapping, max_entries=1))


@frozen
class PermitKeys:
    """
    Model the released broker's independent wrapping-generation allowlist for publication permits.

    Attributes:
        source (KeyService): Independent synthetic key custody.
        generation (str): The only wrapping generation admitted by this gateway grant.
        observed (list[int]): Requested record kinds without input values.
    """

    source: KeyService
    generation: str
    observed: list[int]

    def invoke(self, action: Literal["wrap", "unwrap", "sign"], generation: str, context: Context, payload: bytes) -> bytes:
        """
        Refuse domain keys and all signing/wrapping at the gateway, even if controller code attempts those capabilities.

        Args:
            action (Literal["wrap", "unwrap", "sign"]): Requested key operation.
            generation (str): Synthetic key generation.
            context (Context): Exact record context.
            payload (bytes): Transient operation input.

        Returns:
            bytes: Authorized permit data key only.
        """
        self.observed.append(context.kind)
        if action != "unwrap" or generation != self.generation:
            raise NativeError("denied")
        return self.source.invoke(action, generation, context, payload)
