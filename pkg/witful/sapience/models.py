"""
Define portable provenance for an optional memory projection and review proposals.
"""

from __future__ import annotations

from typing import Literal

from attrs import frozen

from witful.knowledge.models import Relation  # noqa: TC001 - runtime schema introspection


@frozen
class Provenance:
    """
    Identify the exact source interpretation behind a replaceable memory projection.

    Attributes:
        collection_id (str): Explicit stable collection identity, independent of filesystem paths.
        source_id (str): Canonical concept identifier in the collection.
        kind (str): Organizational concept type.
        revision (str): SHA256 of the flattened source representation.
        content_hash (str): SHA256 of projected UTF-8 text.
        observed_at (str | None): Recorded source observation, when one exists.
        supersedes (str | None): Explicit earlier journal identifier.
        source_ref (str | None): Original teaching or evidence reference when recorded.
        parent_id (str | None): Canonical containment parent.
        related_ids (tuple[str, ...]): Source concept IDs, distinct from remote memory IDs.
        relations (tuple[Relation, ...]): Sourced cross-discipline edges incident on this concept.
        status (Literal["active", "historical"]): Whether a later journal record supersedes this concept.
        version (Literal[1]): Projection schema version.
        producer (Literal["witful"]): Source adapter identity.
    """

    collection_id: str
    source_id: str
    kind: str
    revision: str
    content_hash: str
    observed_at: str | None
    supersedes: str | None
    source_ref: str | None
    parent_id: str | None
    related_ids: tuple[str, ...]
    relations: tuple[Relation, ...]
    status: Literal["active", "historical"]
    version: Literal[1] = 1
    producer: Literal["witful"] = "witful"


@frozen
class Memory:
    """
    Describe a complete, reviewable call to Sapience's idempotent upsert tool.

    Attributes:
        memory_id (str): Stable collection, namespace, and concept-derived ID.
        namespace (str): Concrete destination partition.
        content (str): Flattened source text, never a generated lesson.
        topic (str): Source concept display name.
        related_ids (tuple[str, ...]): Deterministic remote IDs for adjacent concepts.
        metadata (Provenance): Source ownership and revision data.
        memory_type (Literal["reference"]): Projection category.
        source (Literal["witful"]): Adapter marker.
        salience (float): Neutral retrieval weight, not a capability score.
    """

    memory_id: str
    namespace: str
    content: str
    topic: str
    related_ids: tuple[str, ...]
    metadata: Provenance
    memory_type: Literal["reference"] = "reference"
    source: Literal["witful"] = "witful"
    salience: float = 0.5


@frozen
class Projection:
    """
    Hold deterministic source projections for inspection before external processing.

    Attributes:
        memories (tuple[Memory, ...]): Ordered concepts including explicitly marked historical guidance.
        version (Literal[1]): Envelope schema version.
    """

    memories: tuple[Memory, ...]
    version: Literal[1] = 1


@frozen
class Brief:
    """
    Validate a generated summary before persisting it as an unreviewed proposal.

    Attributes:
        topic (str): Requested subject.
        namespace (str): Actual retrieval partition.
        summary (str): Model-produced summary, not authoritative guidance.
        memory_count (int): Number of source memories retrieved.
        memory_ids (tuple[str, ...]): Retrieved memory identifiers.
        key_facts (tuple[str, ...]): Generated factual claims requiring review.
        evolved_thinking (tuple[str, ...]): Proposed interpretation of change.
        open_questions (tuple[str, ...]): Generated follow-up questions.
        challenge_points (tuple[str, ...]): Generated critique requiring review.
    """

    topic: str
    namespace: str
    summary: str
    memory_count: int
    memory_ids: tuple[str, ...]
    key_facts: tuple[str, ...] = ()
    evolved_thinking: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    challenge_points: tuple[str, ...] = ()
