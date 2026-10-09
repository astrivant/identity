"""
Compile existing concepts into deterministic external memory records without changing sources.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Literal

from witful.knowledge.compiler import compile_identity, index
from witful.knowledge.contracts import as_data, structure
from witful.knowledge.models import Catalog, Lesson
from witful.lessons import read_journal
from witful.sapience.models import Memory, Projection, Provenance

if TYPE_CHECKING:
    from pathlib import Path


def digest(value: object) -> str:
    """
    Hash canonical JSON for reproducible identifiers and source revisions.

    Args:
        value (object): JSON-compatible value.

    Returns:
        str: SHA256 hexadecimal digest.
    """
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def project(root: Path, collection_id: str, namespace: str) -> Projection:
    """
    Flatten validated hierarchy nodes with containment and cross-discipline provenance.

    Args:
        root (Path): Existing collection directory.
        collection_id (str): Stable user-selected collection ID; keep it unchanged on retries.
        namespace (str): Concrete Sapience namespace, without whitespace or wildcards.

    Returns:
        Projection: Deterministic records; no source files or remote state are changed.

    Raises:
        ValueError: Collection identity or namespace is empty or invalid.
    """
    if not collection_id.strip() or not namespace or len(namespace) > 128 or "*" in namespace or any(c.isspace() for c in namespace):
        raise ValueError("Provide a stable collection ID and concrete namespace without whitespace or '*'")

    catalog = structure(json.loads((root / "knowledge/catalog.json").read_text()), Catalog)
    identity = compile_identity(read_journal(root / "lessons.jsonl"), catalog)
    nodes, parents = index(identity)
    remote_ids = {key: f"witful:{digest([collection_id, namespace, key])}" for key in nodes}
    historical = {node.supersedes for node in nodes.values() if isinstance(node, Lesson) and node.supersedes}
    memories: list[Memory] = []

    for key, node in sorted(nodes.items()):
        # Flatten ownership to avoid copying an entire descendant journal into every ancestor.
        source = {
            field: value
            for field, value in as_data(node).items()
            if field not in {"disciplines", "skills", "lessons", "lemmas", "relations"}
        }
        edges = tuple(edge for edge in identity.relations if key in {edge.source, edge.target})
        related = {child for child, parent in parents.items() if parent == key}
        related.update(edge.target if edge.source == key else edge.source for edge in edges)

        if key in parents:
            related.add(parents[key])

        if isinstance(node, Lesson) and node.supersedes:
            related.add(node.supersedes)

        source_ids = tuple(sorted(related))
        status: Literal["active", "historical"] = "historical" if key in historical or parents.get(key) in historical else "active"
        content = f"{type(node).__name__}: {node.name}\nStatus: {status}"
        statement = source.get("statement")

        if isinstance(statement, str):
            content += f"\n\n{statement}"

        provenance = Provenance(
            collection_id,
            key,
            type(node).__name__.lower(),
            digest(
                {
                    "source": source,
                    "relations": [as_data(edge) for edge in edges],
                    "parent": parents.get(key),
                    "related": source_ids,
                    "status": status,
                }
            ),
            hashlib.sha256(content.encode()).hexdigest(),
            node.observed_at if isinstance(node, Lesson) else None,
            node.supersedes if isinstance(node, Lesson) else None,
            str(source["source"]) if "source" in source else None,
            parents.get(key),
            source_ids,
            edges,
            status,
        )
        memories.append(Memory(remote_ids[key], namespace, content, node.name, tuple(remote_ids[item] for item in source_ids), provenance))

    return Projection(tuple(memories))
