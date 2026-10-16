"""
Validate native domain records with the same closed models and causal contracts as the existing journal adapters.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from attrs import field, frozen
from jsonschema import ValidationError

from witful.checkpoints import journal as checkpoints
from witful.checkpoints.models import Checkpoint
from witful.codegraph.models import Graph
from witful.codegraph.models import validate as validate_graph
from witful.exceptions import NativeError
from witful.instances import journal as instances
from witful.instances.models import Event as InstanceEvent
from witful.knowledge.applications import validate_applications
from witful.knowledge.compiler import compile_identity, index
from witful.knowledge.contracts import structure
from witful.knowledge.models import Application, Catalog
from witful.lessons import parse_journal
from witful.life.contracts import validate_archive
from witful.life.models import Archive, Event, Snapshot
from witful.native.models import Reconciliation
from witful.native.values import pack, unpack
from witful.native.wire import mapping, text
from witful.reflection import journal as reflection
from witful.reflection.models import Review
from witful.repertoire import journal as repertoire
from witful.repertoire.models import Inventory, Use

__all__ = ["Entry", "decode", "encode", "validate"]

MODELS: dict[str, type[object]] = {
    "repository-codegraph": Graph,
    "reconciliation": Reconciliation,
    "catalog": Catalog,
    "application": Application,
    "life-event": Event,
    "life-snapshot": Snapshot,
    "checkpoint": Checkpoint,
    "instance-event": InstanceEvent,
    "repertoire-inventory": Inventory,
    "repertoire-use": Use,
    "reflection-review": Review,
}


@frozen
class Entry:
    """
    Carry one explicit domain record without a writable JSON journal as the native source of truth.

    Attributes:
        domain (str): Closed schema registry key.
        value (object): Validated domain data; excluded from diagnostic representations.
    """

    domain: str
    value: object = field(repr=False)


def encode(entry: Entry) -> object:
    """
    Admit a single registered schema before lossless binary scalar conversion.

    Args:
        entry (Entry): Candidate domain object.

    Returns:
        object: Closed domain envelope suitable for deterministic CBOR and encryption.
    """
    try:
        if entry.domain == "lesson":
            # A superseding lesson needs its complete preceding chain; validate that in validate().
            fields = {"id", "topic", "lesson", "source", "observed_at", "supersedes"}
            mapping(entry.value, fields)
        elif entry.domain in MODELS:
            model = structure(entry.value, MODELS[entry.domain])
            if isinstance(model, Graph):
                validate_graph(model)
        else:
            raise NativeError("unsupported")
        return {"domain": entry.domain, "value": pack(entry.value)}
    except (ValueError, TypeError, ValidationError):
        raise NativeError("invalid") from None


def decode(value: object) -> Entry:
    """
    Decode an authenticated domain payload and revalidate its closed schema.

    Args:
        value (object): Decrypted native CBOR value.

    Returns:
        Entry: Validated domain schema with lossless finite scalar values.
    """
    body = mapping(value, {"domain", "value"})
    entry = Entry(text(body["domain"]), unpack(body["value"]))
    encode(entry)
    return entry


def validate(entries: tuple[Entry, ...]) -> None:
    """
    Validate the selected first-parent view without concatenating competing journal branches.

    Args:
        entries (tuple[Entry, ...]): Complete selected causal state, ordered oldest first.

    Returns:
        None: Existing source invariants and cross-domain references hold without filesystem materialization.
    """
    grouped: dict[str, list[object]] = {}
    for entry in entries:
        encode(entry)
        grouped.setdefault(entry.domain, []).append(entry.value)
    try:
        lessons = parse_journal("\n".join(json.dumps(value) for value in grouped.get("lesson", [])))
        catalogs = grouped.get("catalog", [])
        identity = compile_identity(lessons, structure(catalogs[-1], Catalog)) if catalogs else None
        applications = tuple(structure(value, Application) for value in grouped.get("application", []))
        uses = tuple(structure(value, Use) for value in grouped.get("repertoire-use", []))
        if identity is None and (applications or uses):
            raise NativeError("incomplete")
        if identity is not None:
            validate_applications(identity, applications)
        snapshots = tuple(structure(value, Snapshot) for value in grouped.get("life-snapshot", []))
        events = tuple(structure(value, Event) for value in grouped.get("life-event", []))
        validate_archive(Archive(events, tuple(sorted(snapshots, key=lambda item: item.id))))
        checkpoints.validate(tuple(structure(value, Checkpoint) for value in grouped.get("checkpoint", [])))
        instances.validate(tuple(structure(value, InstanceEvent) for value in grouped.get("instance-event", [])))
        inventories = grouped.get("repertoire-inventory", [])
        inventory = structure(inventories[-1], Inventory) if inventories else Inventory()
        repertoire.validate(inventory, uses, set(index(identity)[0]) if identity is not None else set())
        reflection.validate(
            tuple(structure(value, Review) for value in grouped.get("reflection-review", [])), {event.id for event in events}
        )
        # This round trip keeps the legacy lesson hash representation independently checkable.
        if lessons and [asdict(value) for value in lessons] != grouped["lesson"]:
            raise NativeError("invalid")
    except (ValueError, TypeError, KeyError, ValidationError):
        raise NativeError("invalid") from None
