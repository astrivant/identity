"""
Define separate, closed context contracts without changing catalog or historical journal serialization.
"""

from __future__ import annotations

from typing import Literal

from attrs import frozen


@frozen
class Scope:
    """
    Partition a locally authorized collection and permission snapshot.

    Attributes:
        identity (str): Canonical identity ID.
        collection (str): Opaque collection reference, not a filesystem path.
        domain (str): Confidentiality boundary, independent of discipline labels.
        permission (str): Reviewed access-policy revision.
    """

    identity: str
    collection: str
    domain: str
    permission: str


@frozen
class Descriptor:
    """
    Bind one coherent work step without storing raw prompts or tool payloads.

    Attributes:
        scope (Scope): Requested collection and permission boundary.
        task (str): Stable opaque task reference.
        phase (str): Current work phase.
        action (str): Intended action class, never an authorization grant.
        context_id (str): Runtime context generation; change after compaction, resume, or delegation.
        concepts (tuple[str, ...]): Explicitly selected canonical concepts.
        tags (tuple[str, ...]): Reviewed bounded task vocabulary.
        paths (tuple[str, ...]): Workspace-relative POSIX paths used only for matching.
        resources (tuple[str, ...]): Resource classes used by reviewed rules.
        terms (tuple[str, ...]): Terms for exact normalized semantic aliases, not free-text ranking.
        evidence_revision (str): Change when failures, reviews, or new evidence affect applicability.
        instance (str): Actual instance reference, empty when unknown.
        sleeve (str): Actual sleeve reference, empty when unknown.
        refresh_trigger (str): Why this context generation was selected.
        prior_receipt (str): Previous receipt content digest, empty for an initial resolution.
    """

    scope: Scope
    task: str
    phase: str
    action: str
    context_id: str
    concepts: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    terms: tuple[str, ...] = ()
    evidence_revision: str = ""
    instance: str = ""
    sleeve: str = ""
    refresh_trigger: str = "initial"
    prior_receipt: str = ""


@frozen
class Rule:
    """
    Map reviewed selectors additively to canonical concepts.

    Attributes:
        id (str): Stable rule identifier.
        concepts (tuple[str, ...]): Canonical seeds selected when this rule matches.
        source (str): Review provenance for the mapping, never executable instructions.
        priority (int): Stable ordering only; never removes overlapping matches.
        tags (tuple[str, ...]): Any matching tag satisfies this selector dimension.
        paths (tuple[str, ...]): Case-sensitive POSIX fnmatch patterns over relative paths.
        phases (tuple[str, ...]): Allowed phases; empty means unrestricted.
        actions (tuple[str, ...]): Allowed action classes; empty means unrestricted.
        resources (tuple[str, ...]): Allowed resource classes; empty means unrestricted.
        terms (tuple[str, ...]): Exact NFKC/casefold/whitespace-normalized vocabulary aliases.
    """

    id: str
    concepts: tuple[str, ...]
    source: str
    priority: int = 0
    tags: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    phases: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    terms: tuple[str, ...] = ()


@frozen
class Limits:
    """
    Bound execution using explicit fixture defaults rather than production sizing claims.

    Attributes:
        nodes (int): Maximum candidate metadata nodes.
        edges (int): Maximum relation edges inspected.
        text_bytes (int): Maximum exact statement/provenance bytes loaded.
        tokens (int): Conservative UTF-8-byte token upper bound; no tokenizer dependency.
        source_reads (int): Maximum caller-observed source reads.
        elapsed_ms (int): Maximum caller-observed retrieval duration.
        optional_hops (Literal[0, 1]): Optional relation expansion depth per selected or required origin.
        max_age_seconds (int): Snapshot observation age limit; zero disables this policy.
        require_live (bool): Require independently supplied current live evidence.
    """

    nodes: int = 2000
    edges: int = 8000
    text_bytes: int = 1048576
    tokens: int = 8000
    source_reads: int = 100
    elapsed_ms: int = 2000
    optional_hops: Literal[0, 1] = 1
    max_age_seconds: int = 0
    require_live: bool = False


@frozen
class Mapping:
    """
    Bind reviewed rules to one authorized source snapshot in a versioned sidecar.

    Attributes:
        scope (Scope): Independently reviewed local access boundary.
        hierarchy_digest (str): Exact compiled catalog/journal digest.
        rules (tuple[Rule, ...]): Additive reviewed selectors.
        global_concepts (tuple[str, ...]): Constraints that explicit task selection cannot remove.
        limits (Limits): Reviewed execution and freshness profile.
        version (Literal[1]): Independent sidecar schema version.
    """

    scope: Scope
    hierarchy_digest: str
    rules: tuple[Rule, ...] = ()
    global_concepts: tuple[str, ...] = ()
    limits: Limits = Limits()
    version: Literal[1] = 1


@frozen
class Observation:
    """
    Supply external state once at the orchestration boundary.

    Attributes:
        source_revision (str): Last verified collection commit, with content separately hashed.
        workspace_digest (str): Fingerprint of selected workspace revisions, index, and dirty files.
        observed_at (int): Actual original source-snapshot observation time in Unix seconds.
        verified_at (int): Current verification time; does not renew source observations.
        source_reads (int): Source reads already consumed, supplied by the adapter.
        elapsed_ms (int): Retrieval duration already consumed, supplied by the adapter.
        live_evidence (str): Independent live-check evidence reference; empty means unavailable.
        offline (bool): Whether remote freshness is unknown.
    """

    source_revision: str
    workspace_digest: str
    observed_at: int
    verified_at: int
    source_reads: int = 2
    elapsed_ms: int = 0
    live_evidence: str = ""
    offline: bool = True


@frozen
class Decision:
    """
    Record an individual applicability judgment, never inherited from a parent checkbox.

    Attributes:
        id (str): Canonical candidate identifier.
        status (Literal["applicable", "not_applicable", "blocked", "deferred"]): Reviewed disposition.
        reason (str): Scoped rationale, including the blocked next action when relevant.
        source (str): Reviewer or evidence reference supporting this decision.
    """

    id: str
    status: Literal["applicable", "not_applicable", "blocked", "deferred"]
    reason: str
    source: str


@frozen
class Candidate:
    """
    Preserve metadata, exact loaded text, and deterministic reasons for inclusion.

    Attributes:
        id (str): Canonical concept ID.
        parent (str | None): Canonical owner.
        kind (str): Existing hierarchy node type.
        name (str): Local private display name.
        status (str): Review disposition, pending, or historical.
        required (bool): Selected/global/dependency context cannot be excluded or deferred.
        paths (tuple[str, ...]): Typed traversal reasons, independent of visual geometry.
        reason (str): Explicit reviewer reason or supersession explanation.
        evidence (str): Applicability evidence reference.
        statement (str): Exact authoritative text when loaded; never a summary.
        source (str): Exact teaching provenance when loaded.
        text_digest (str): SHA-256 of exact statement and source; empty when not loaded.
    """

    id: str
    parent: str | None
    kind: str
    name: str
    status: str
    required: bool
    paths: tuple[str, ...]
    reason: str = ""
    evidence: str = ""
    statement: str = ""
    source: str = ""
    text_digest: str = ""


@frozen
class Receipt:
    """
    Report working-context coverage independently of authorization and final completion.

    Attributes:
        binding (str): Digest of source, mapping, descriptor, workspace, and resolver version.
        content_digest (str): Deterministic receipt content digest excluding operational timestamps.
        state (Literal["complete", "incomplete", "unmapped", "invalid"]): Coverage result only.
        descriptor (Descriptor | None): Inspectable task, permission, instance and refresh bindings after access validation.
        hierarchy_digest (str): Canonical source-content fingerprint.
        mapping_digest (str): Reviewed sidecar fingerprint.
        source_revision (str): Last locally observed collection commit.
        workspace_digest (str): Actual selected workspace fingerprint.
        limits (Limits | None): Reviewed execution profile.
        source_reads (int): Consumed source-document reads, excluding workspace hashing.
        elapsed_ms (int): Measured adapter retrieval time, excluded from deterministic content hashing.
        next_action (str): Action awaiting coverage, empty when coverage is complete.
        matched_rules (tuple[str, ...]): Matching reviewed rule IDs in stable priority order.
        seeds (tuple[str, ...]): Selected concepts including globals.
        candidates (tuple[Candidate, ...]): Enumerated candidates in prerequisite-first order.
        loaded (tuple[str, ...]): Exact texts supplied to the caller.
        unmet (tuple[str, ...]): Unreviewed, conflicting, or unloaded required candidates.
        blockers (tuple[str, ...]): Bounded diagnostics; denied access has no target metadata.
        text_bytes (int): Exact loaded statement and provenance bytes.
        context_bytes (int): UTF-8 bytes of compact descriptor, candidates, seeds, and matched-rule context.
        observed_at (int): Original snapshot observation timestamp.
        verified_at (int): Current receipt verification timestamp.
        offline (bool): Local snapshot coverage cannot establish unseen remote state.
        resolver (Literal["context-v1"]): Algorithm version.
        tokenizer (Literal["utf8-byte-upper-bound-v1"]): Conservative token accounting policy.
        advisory (bool): No runtime pre-action enforcement is installed.
        version (Literal[1]): Receipt schema version.
    """

    binding: str
    content_digest: str
    state: Literal["complete", "incomplete", "unmapped", "invalid"]
    descriptor: Descriptor | None = None
    hierarchy_digest: str = ""
    mapping_digest: str = ""
    source_revision: str = ""
    workspace_digest: str = ""
    limits: Limits | None = None
    source_reads: int = 0
    elapsed_ms: int = 0
    next_action: str = ""
    matched_rules: tuple[str, ...] = ()
    seeds: tuple[str, ...] = ()
    candidates: tuple[Candidate, ...] = ()
    loaded: tuple[str, ...] = ()
    unmet: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    text_bytes: int = 0
    context_bytes: int = 0
    observed_at: int = 0
    verified_at: int = 0
    offline: bool = True
    resolver: Literal["context-v1"] = "context-v1"
    tokenizer: Literal["utf8-byte-upper-bound-v1"] = "utf8-byte-upper-bound-v1"
    advisory: bool = True
    version: Literal[1] = 1


@frozen
class Review:
    """
    Carry sourced applicability judgments in a closed JSON document.

    Attributes:
        decisions (tuple[Decision, ...]): Individual candidate decisions, with no inherited approvals.
        version (Literal[1]): Review schema version.
    """

    decisions: tuple[Decision, ...] = ()
    version: Literal[1] = 1
