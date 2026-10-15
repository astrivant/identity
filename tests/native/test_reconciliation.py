"""
Keep reviewed branch adoption distinct from automatic union of immutable journals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from witful.exceptions import NativeError
from witful.native.authority import Authority
from witful.native.reconciliation import Selection, merge

from tests.native.runtime import branches, lesson

if TYPE_CHECKING:
    from witful.native.authority import Access
    from witful.native.storage import Head, Store

    from tests.native.database import Databases
    from tests.native.runtime import Runtime


def test_explicit_adoption_preserves_both_histories(runtime: Runtime) -> None:
    """
    Keep original branch bytes and hashes while recording ordered native ancestry and an explicit new adoption mapping.

    Args:
        runtime (Runtime): Real supported storage backend.

    Returns:
        None: Both histories remain intact and an identical review retry has one receipt.
    """
    service, access = runtime.service, runtime.access
    target, candidate = branches(runtime)
    before = service.history(access, "candidate")
    operation = str(uuid4())
    selections = (Selection((candidate,), lesson("candidate")),)
    receipt = merge(service, access, operation, "main", "candidate", target, candidate, selections, "Reviewed synthetic evidence")
    assert merge(service, access, operation, "main", "candidate", target, candidate, selections, "Reviewed synthetic evidence") == receipt
    after = service.history(access, "main")
    assert [entry for _, entry in after if entry.domain == "lesson"] == [lesson("base"), lesson("target"), lesson("candidate")]
    resolution, decision = next(item for item in after if item[1].domain == "reconciliation")
    assert resolution.parents == (target, candidate)
    assert isinstance(decision.value, dict) and decision.value["reviewer"] == access.subject
    assert service.history(access, "candidate") == before
    with pytest.raises(NativeError, match="denied"):
        service.append(access, str(uuid4()), "main", after[-1][0].id, (decision,))
    with pytest.raises(NativeError, match="conflict"):
        merge(service, access, str(uuid4()), "main", "candidate", target, candidate, (), "Stale review")


def test_review_permission_is_rechecked_after_prepare(runtime: Runtime, databases: Databases, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Revoke the special action between durable prepare and apply and prove ordinary write permission cannot finish it.

    Args:
        runtime (Runtime): Real supported backend.
        databases (Databases): Independent synthetic policy administrator.
        monkeypatch (pytest.MonkeyPatch): Deterministic boundary injection without timing sleeps.

    Returns:
        None: The mutation is denied, its durable candidate remains recoverable and no unreviewed adoption is published.
    """
    service, access = runtime.service, runtime.access
    target, candidate = branches(runtime)
    expected = service.store.head(access.scope)
    original = Authority.apply

    def revoke(authority: Authority, request: Access, store: Store, now: int) -> Head:
        """
        Remove review at the exact post-prepare boundary, then call the real fenced apply.

        Args:
            authority (Authority): Actual authority implementation.
            request (Access): Prepared request bindings.
            store (Store): Actual data backend.
            now (int): Observed admission time.

        Returns:
            Head: Never succeeds for the now-revoked review.
        """
        with psycopg.connect(databases.authority_admin) as admin:
            admin.execute("UPDATE witful_native_grants SET actions = array_remove(actions, 'review') WHERE id = %s", (access.grant,))
        return original(authority, request, store, now)

    monkeypatch.setattr(Authority, "apply", revoke)
    with pytest.raises(NativeError, match="denied"):
        merge(
            service,
            access,
            str(uuid4()),
            "main",
            "candidate",
            target,
            candidate,
            (Selection((candidate,), lesson("candidate")),),
            "Explicit review",
        )
    assert service.store.head(access.scope) == expected
    assert service.authority.recover(access, service.store, int(service.clock())) == expected
    assert service.history(access, "main")[-1][0].id == target
