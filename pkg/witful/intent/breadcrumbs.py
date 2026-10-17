"""
Project explicit source comments into unreviewed documentation dependencies.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from attrs import evolve

from witful.exceptions import NativeError
from witful.intent.docrefs import discover
from witful.intent.models import Anchor, Assertion, Evidence

if TYPE_CHECKING:
    from collections.abc import Mapping

    from witful.intent.models import State


def attach(state: State, sources: Mapping[str, bytes], now: int) -> State:
    """
    Retain exact declarations and reverse consumer edges without inventing semantic approval.

    Args:
        state (State): Draft already bound to an admitted graph and exact manifest.
        sources (Mapping[str, bytes]): Admitted non-excluded source bytes, read inside the protected runtime.
        now (int): Actual preparation time supplied by the runtime.

    Returns:
        State: New immutable draft with declaration evidence and inferred consumer assertions.

    Raises:
        NativeError: Markers are invalid, consumers are excluded/missing, or source bytes do not match the manifest.
    """
    files = {item.path: item for item in state.files if item.disposition == "source"}
    for path, raw in sources.items():
        file = files.get(path)
        if file is None or file.digest != hashlib.sha256(raw).hexdigest() or file.size != len(raw):
            raise NativeError("conflict")
    try:
        declarations = discover(sources)
    except (ValueError, UnicodeError) as error:
        raise NativeError("invalid") from error
    anchors = list(state.anchors)
    evidence = list(state.evidence)
    assertions = list(state.assertions)
    for item in declarations:
        key = "docref:" + item.id
        source = Anchor("anchor:" + key, item.path, item.digest, item.start, item.end, "pygments", "docref/1")
        anchors.append(source)
        declaration = Evidence(
            "evidence:" + key,
            "intent_declaration",
            source.id,
            hashlib.sha256(item.text.encode()).hexdigest(),
            "source:" + item.path,
            now,
            (source.id,),
            item.text,
        )
        evidence.append(declaration)
        for consumer in item.consumers:
            file = files.get(consumer)
            if file is None or consumer not in sources:
                raise NativeError("incomplete")
            identifier = key + ":" + hashlib.sha256(consumer.encode()).hexdigest()
            document = Anchor("anchor:" + identifier, consumer, file.digest, 0, file.size, "docref/1", "declared-consumer")
            anchors.append(document)
            assertions.append(
                Assertion(
                    "assertion:" + identifier,
                    "",
                    (document.id,),
                    f"{consumer} documents {item.id} in {item.path}.",
                    "Declared documentation dependency; link location and semantic agreement require review",
                    "declaration",
                    (declaration.id,),
                    (),
                    (source.id,),
                    (),
                    now,
                    (item.id, consumer),
                )
            )
    return evolve(state, anchors=tuple(anchors), evidence=tuple(evidence), assertions=tuple(assertions))
