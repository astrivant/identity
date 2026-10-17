"""
Verify source breadcrumbs become unreviewed, source-bound reverse dependencies.
"""

from __future__ import annotations

import hashlib

import pytest
from attrs import evolve
from witful.context.models import Limits
from witful.exceptions import NativeError
from witful.intent.breadcrumbs import attach
from witful.intent.contracts import fingerprint, validate
from witful.intent.core import affected, resolve
from witful.intent.models import File, Query

from tests.intent.support import example


def test_breadcrumb_dependencies() -> None:
    """
    Surface document consumers when their source changes without granting semantic verification.

    Returns:
        None: Both retained evidence bytes and reverse edges are checked.
    """
    raw = b"# docref:1 model -> docs/api.md\nclass Model: pass\n"
    sources = {"a.py": raw, "docs/api.md": b"Read [Model][code:model].\n"}
    base = example()
    files = tuple(
        sorted(
            (*base.files, *(File(path, hashlib.sha256(data).hexdigest(), len(data)) for path, data in sources.items())),
            key=lambda f: f.path,
        )
    )
    base = evolve(
        base,
        files=files,
        scope=evolve(base.scope, manifest=fingerprint(files)),
        coverage=tuple(evolve(item, manifest=fingerprint(files)) for item in base.coverage),
    )
    state = attach(base, sources, 101)
    validate(state)
    assert state.reviews == base.reviews and state.coverage == base.coverage
    assertion = state.assertions[-1]
    assert assertion.id in affected(state, ("anchor:docref:model",))
    evidence = state.evidence[-1]
    anchor = next(item for item in state.anchors if item.id == evidence.source)
    assert hashlib.sha256(raw[anchor.start : anchor.end]).hexdigest() == evidence.digest
    result = resolve(state, Query("find", "model", view="both"), Limits(tokens=100000, text_bytes=100000), 102)
    assert any(claim.assertion.id == assertion.id and claim.projection == "inferred" for claim in result.claims)
    with pytest.raises(NativeError):
        attach(base, {**sources, "a.py": raw + b"changed"}, 102)
    with pytest.raises(NativeError):
        attach(base, {"a.py": raw}, 102)
