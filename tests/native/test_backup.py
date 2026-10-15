"""
Verify complete encrypted restore across backends and lossless finite scalar representation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from attrs import evolve
from witful.exceptions import NativeError
from witful.native import codec
from witful.native.backup import Archive, archive, restore
from witful.native.git import Git, git
from witful.native.postgres import Postgres
from witful.native.values import pack, unpack

from tests.native.runtime import lesson

if TYPE_CHECKING:
    from pathlib import Path

    from witful.native.storage import Store

    from tests.native.database import Databases
    from tests.native.runtime import Runtime


def test_restore_full_history_other_backend(runtime: Runtime, databases: Databases, tmp_path: Path) -> None:
    """
    Preserve exact original receipts, refs, semantic records and source bytes through encrypted backup and cross-backend restore.

    Args:
        runtime (Runtime): Real source service.
        databases (Databases): Isolated PostgreSQL destination when the source is Git.
        tmp_path (Path): Explicit synthetic ciphertext workspace.

    Returns:
        None: The independently restored backend has identical retained history and rejects divergence.
    """
    service, access = runtime.service, runtime.access
    service.append(access, str(uuid4()), "main", None, (lesson(),), b"original source bytes")
    revision = service.history(access, "main")[-1][0].id
    service.branch(access, str(uuid4()), "retained", revision, immutable=True)
    context, ciphertext = archive(service, access)
    assert b"original source bytes" not in ciphertext
    target: Store
    if isinstance(service.store, Git):
        target = Postgres(databases.data)
    else:
        directory = tmp_path / "restored.git"
        directory.mkdir()
        git(directory, ("init", "--bare", "."))
        target = Git(directory, "Synthetic Contract", "contract@example.invalid")
    result = restore(service, access, context, ciphertext, target)
    assert result == service.store.head(access.scope)
    assert target.history(access.scope) == service.store.history(access.scope)
    assert restore(service, access, context, ciphertext, target) == result
    # Result verification can use a separate physical reader without granting that backend authority.
    assert evolve(service, store=target).history(access, "retained") == service.history(access, "retained")
    with pytest.raises(NativeError):
        restore(service, access, evolve(context, record=str(uuid4())), ciphertext, target)


def test_archive_rejects_dropped_middle_transaction(runtime: Runtime) -> None:
    """
    Detect incomplete recovery history rather than treating the newest frontier as sufficient backup evidence.

    Args:
        runtime (Runtime): Real native source.

    Returns:
        None: A skipped predecessor prevents restore before mutation.
    """
    service, access = runtime.service, runtime.access
    service.append(access, str(uuid4()), "main", None, (lesson(),))
    revision = service.history(access, "main")[-1][0].id
    service.branch(access, str(uuid4()), "copy", revision)
    with pytest.raises(NativeError):
        Archive(access.scope, service.store.history(access.scope)[1:]).encode(codec.Limits())


@pytest.mark.parametrize(
    "value", (0.0, -0.0, 0.1, 1.7976931348623157e308, 5e-324, {"nested": [True, None, 3, "hex", {"tag": [3, "0x1p0"]}]})
)
def test_typed_scalar_round_trip(value: object) -> None:
    """
    Preserve finite binary64 values and ordinary maps without sentinel collisions.

    Args:
        value (object): Domain scalar or nested tree.

    Returns:
        None: The canonical typed representation round-trips through real CBOR.
    """
    packed = pack(value)
    restored = unpack(codec.decode(codec.encode(packed)))
    assert pack(restored) == packed


@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf")))
def test_nonfinite_domain_values_rejected(value: float) -> None:
    """
    Reject nonfinite values before encryption or persistence.

    Args:
        value (float): Unsupported nonfinite number.

    Returns:
        None: Invalid domain scalars cannot enter the persisted codec.
    """
    with pytest.raises(NativeError):
        pack(value)


def test_noncanonical_float_encoding_rejected() -> None:
    """
    Reject alternate spellings even when the host float parser accepts them.

    Returns:
        None: One finite value has one admitted typed encoding.
    """
    with pytest.raises(NativeError):
        unpack([3, "0x1p0"])
