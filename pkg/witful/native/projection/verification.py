"""
Cross-check exact candidate objects and signed permits without depending on live storage or delivery transports.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from witful.exceptions import NativeError
from witful.native.kinds import BACKUP
from witful.native.models import parse
from witful.native.projection.bundle import Bundle, validate
from witful.native.projection.models import BUNDLE, PERMIT, Permit
from witful.native.wire import binary

if TYPE_CHECKING:
    from witful.native.projection.models import Prepared
    from witful.native.views import View


def candidate(view: View, prepared: Prepared) -> tuple[Bundle, Permit]:
    """
    Verify every retained binding against original accepted scope, exact Git bytes and independent ciphertext signer pins.

    Args:
        view (View): Authorized live reader or independent offline archive verifier.
        prepared (Prepared): Authenticated pending metadata.

    Returns:
        tuple[Bundle, Permit]: Fully cross-checked candidate; current delivery authorization remains separate.
    """
    if prepared.bundle.kind != BUNDLE or prepared.permit.kind != PERMIT:
        raise NativeError("invalid")
    raw = binary(view.open(prepared.bundle))
    bundle = Bundle.decode(raw, view.keys.limits)
    permit = parse(view.open(prepared.permit), Permit)
    record = str(uuid5(UUID(prepared.intent.operation), prepared.intent.target.id))
    validate(bundle, record, prepared.expected, prepared.author, prepared.email, prepared.recorded)
    blob, tree, commit = bundle.objects()
    if (
        permit.intent != prepared.intent
        or permit.expected != prepared.expected
        or (permit.author, permit.email, permit.recorded) != (prepared.author, prepared.email, prepared.recorded)
        or permit.digest != hashlib.sha256(raw).hexdigest()
        or permit.oid != prepared.oid
        or (blob[1], tree[1], commit[1]) != (prepared.blob, prepared.tree, prepared.oid)
        or permit.context.kind != BACKUP
        or permit.context.record != record
        or (permit.context.tenant, permit.context.identity) != (view.scope.tenant, view.scope.identity)
    ):
        raise NativeError("invalid")
    view.keys.verify(permit.context, bundle.blob)
    return bundle, permit
