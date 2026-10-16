"""
Define closed immutable intent, evidence, coverage and discovery contracts.
"""

from __future__ import annotations

from typing import Literal

from attrs import frozen

from witful.context.models import Limits  # noqa: TC001 - closed schema introspection needs the runtime type
from witful.repertoire.models import Inventory  # noqa: TC001 - closed schema construction resolves this type at runtime

EvidenceKind = Literal["intent_declaration", "source_inspection", "test_result", "runtime_observation", "inference", "mandatory_teaching"]


@frozen
class Scope:
    """
    Bind every fact to one protected repository generation.

    Attributes:
        tenant (str): Native tenant UUID.
        owner (str): Owning identity UUID, not a grant.
        repository (str): Opaque enrolled extension UUID.
        revision (str): Exact clean source commit.
        manifest (str): Digest of the complete source manifest.
        graph (str): Exact CodeGraph generation UUID.
        schema (Literal["intent/1"]): Closed intent schema.
    """

    tenant: str
    owner: str
    repository: str
    revision: str
    manifest: str
    graph: str
    schema: Literal["intent/1"] = "intent/1"


@frozen
class Input:
    """
    Register derivation inputs and explicit freshness requirements.

    Attributes:
        id (str): Stable qualified input ID.
        kind (str): Configuration, inventory, parser, query, policy or observation class.
        digest (str): SHA-256 of the observed content or redacted state.
        observed (int): UTC epoch seconds of actual observation.
        expires (int | None): Exclusive validity horizon, if defined.
        live (bool): Require a matching independent observation on every consumption.
        available (bool): Whether this admitted input can currently be inspected.
    """

    id: str
    kind: str
    digest: str
    observed: int
    expires: int | None = None
    live: bool = False
    available: bool = True


@frozen
class File:
    """
    Define the exact byte universe independently of semantic inspection.

    Attributes:
        path (str): Canonical repository-relative path.
        digest (str): SHA-256 of exact bytes.
        size (int): Complete file byte length.
        disposition (Literal["source", "generated", "excluded", "unsupported"]): Visible denominator classification.
    """

    path: str
    digest: str
    size: int
    disposition: Literal["source", "generated", "excluded", "unsupported"] = "source"


@frozen
class Anchor:
    """
    Bind a source reference to exact bytes, never a bare symbol name.

    Attributes:
        id (str): Generation-qualified anchor ID.
        path (str): Path in the declared manifest.
        digest (str): Exact whole-file SHA-256.
        start (int): Inclusive byte offset.
        end (int): Exclusive byte offset.
        parser (str): Parser or direct-inspection version.
        method (str): Extraction method, separate from semantic reading.
        symbol (str): Optional CodeGraph-local symbol ID.
    """

    id: str
    path: str
    digest: str
    start: int
    end: int
    parser: str
    method: str
    symbol: str = ""


@frozen
class Span:
    """
    Partition a declared file universe without double-counting exclusions.

    Attributes:
        path (str): Manifest path.
        start (int): Inclusive byte offset.
        end (int): Exclusive byte offset.
        state (Literal["inspected", "uninspected", "unavailable", "excluded"]): Independent inspection disposition.
    """

    path: str
    start: int
    end: int
    state: Literal["inspected", "uninspected", "unavailable", "excluded"]


@frozen
class Coverage:
    """
    Retain a question-scoped semantic inspection receipt.

    Attributes:
        id (str): Immutable receipt ID.
        manifest (str): Exact manifest digest.
        spans (tuple[Span, ...]): Complete nonoverlapping partition of the named files.
        files (tuple[str, ...]): Explicit denominator, which may be a subset of the repository.
        method (Literal["semantic", "retrieved", "parsed", "summarized", "truncated"]): Only semantic inspection can mark bytes inspected.
        inspector (str): Attributed reviewer or process, never inferred from credentials.
        question (str): Narrow question being inspected.
        limitations (tuple[str, ...]): Explicit exclusions and uncertainty.
        observed (int): Actual inspection time.
    """

    id: str
    manifest: str
    spans: tuple[Span, ...]
    files: tuple[str, ...]
    method: Literal["semantic", "retrieved", "parsed", "summarized", "truncated"]
    inspector: str
    question: str
    limitations: tuple[str, ...]
    observed: int


@frozen
class Evidence:
    """
    Keep evidence classes and provenance independent from claim verification.

    Attributes:
        id (str): Immutable evidence ID.
        kind (EvidenceKind): Evidence class, not an assertion of correctness.
        source (str): Scoped maintained source reference.
        digest (str): SHA-256 of exact retained content or independently referenced evidence.
        origin (str): Common provenance root used to reject dependent corroboration.
        produced (int): Actual evidence time.
        dependencies (tuple[str, ...]): All known derivation inputs, anchors and evidence.
        text (str): Exact optional teaching or source text; no hidden reasoning.
    """

    id: str
    kind: EvidenceKind
    source: str
    digest: str
    origin: str
    produced: int
    dependencies: tuple[str, ...]
    text: str = ""


@frozen
class Assertion:
    """
    Retain code intent separately from its review history and optional tool binding.

    Attributes:
        id (str): Immutable claim ID.
        tool (str): Canonical repertoire Tool ID when applicable; empty for ordinary code intent.
        anchors (tuple[str, ...]): Exact source anchor IDs.
        statement (str): Narrow intent statement.
        applicability (str): Explicit scope of the claim.
        origin (Literal["declaration", "inference"]): How the candidate was nominated, never its verification status.
        support (tuple[str, ...]): Supporting evidence IDs.
        counter (tuple[str, ...]): Known counterevidence IDs, always included.
        dependencies (tuple[str, ...]): Configuration, toolchain and other claim inputs.
        predecessors (tuple[str, ...]): Explicit superseded assertion IDs; retained as history.
        asserted (int): Actual recording time.
        aliases (tuple[str, ...]): Reviewed discovery vocabulary, never executable commands.
    """

    id: str
    tool: str
    anchors: tuple[str, ...]
    statement: str
    applicability: str
    origin: Literal["declaration", "inference"]
    support: tuple[str, ...]
    counter: tuple[str, ...]
    dependencies: tuple[str, ...]
    predecessors: tuple[str, ...]
    asserted: int
    aliases: tuple[str, ...] = ()


@frozen
class Review:
    """
    Append a semantic judgment with authenticated reviewer attribution.

    Attributes:
        id (str): Immutable review ID.
        assertion (str): Exact assertion reviewed.
        criterion (str): Named versioned review criterion.
        sources (tuple[str, ...]): Maintained intent-declaration evidence IDs.
        result (Literal["supported", "disputed", "refuted", "withdrawn"]): Explicit semantic judgment.
        reason (str): Concise rationale, never hidden reasoning.
        reviewer (str): Actual mTLS peer fingerprint assigned by the server.
        authority (str): Current native grant/policy/task binding assigned by the server.
        reviewed (int): Server-recorded review time.
        predecessor (str): Previous review ID for this assertion, if any.
        binding (str): Exact source and input digest assigned by the server; never silently renewed.
    """

    id: str
    assertion: str
    criterion: str
    sources: tuple[str, ...]
    result: Literal["supported", "disputed", "refuted", "withdrawn"]
    reason: str
    reviewer: str
    authority: str
    reviewed: int
    predecessor: str = ""
    binding: str = ""


@frozen
class Bundle:
    """
    Define one complete conjunctive witness without mixing alternatives.

    Attributes:
        id (str): Stable witness alternative ID.
        members (tuple[str, ...]): Complete AND evidence or nested requirement IDs.
    """

    id: str
    members: tuple[str, ...]


@frozen
class Requirement:
    """
    Freeze a reviewed witness choice and adequacy contract.

    Attributes:
        id (str): Stable requirement ID.
        criterion (str): Versioned adequacy criterion.
        bundles (tuple[Bundle, ...]): OR alternatives, each containing a complete AND witness.
        selected (str): Explicit reviewed alternative; empty means unresolved.
        kinds (tuple[EvidenceKind, ...]): Required evidence classes across the complete selected witness.
        independent (bool): Require distinct provenance roots for leaf evidence.
        allow_empty (bool): Whether this criterion explicitly requires no evidence.
        disclose_missing (bool): Permit naming this requirement, never missing member IDs, in blocked results.
    """

    id: str
    criterion: str
    bundles: tuple[Bundle, ...]
    selected: str
    kinds: tuple[EvidenceKind, ...]
    independent: bool = False
    allow_empty: bool = False
    disclose_missing: bool = False


@frozen
class Dependency:
    """
    Connect a consumer to all mandatory prerequisites.

    Attributes:
        consumer (str): Scoped assertion, evidence, review or requirement ID.
        prerequisites (tuple[str, ...]): Complete mandatory AND prerequisite set.
    """

    consumer: str
    prerequisites: tuple[str, ...]


@frozen
class State:
    """
    Retain immutable intent history and a canonical repertoire snapshot in ciphertext.

    Attributes:
        scope (Scope): One admitted repository and source generation.
        inventory (Inventory): Snapshot of canonical repertoire models; discovery never mutates inventory or usage.
        inputs (tuple[Input, ...]): Complete declared derivation and observation inputs.
        files (tuple[File, ...]): Exact source inspection universe.
        anchors (tuple[Anchor, ...]): Qualified references.
        coverage (tuple[Coverage, ...]): Append-only inspection receipts.
        evidence (tuple[Evidence, ...]): Typed append-only evidence.
        assertions (tuple[Assertion, ...]): Retained candidates, including superseded assertions.
        reviews (tuple[Review, ...]): Authenticated append-only review chain.
        requirements (tuple[Requirement, ...]): Reviewed complete witness alternatives.
        dependencies (tuple[Dependency, ...]): Mandatory dependency edges.
        globals (tuple[str, ...]): Requirements applying to every discovery result.
    """

    scope: Scope
    inventory: Inventory
    inputs: tuple[Input, ...]
    files: tuple[File, ...]
    anchors: tuple[Anchor, ...]
    coverage: tuple[Coverage, ...]
    evidence: tuple[Evidence, ...]
    assertions: tuple[Assertion, ...]
    reviews: tuple[Review, ...]
    requirements: tuple[Requirement, ...]
    dependencies: tuple[Dependency, ...]
    globals: tuple[str, ...] = ()


@frozen
class Observation:
    """
    Supply an independent consumption-boundary observation without credentials.

    Attributes:
        id (str): Existing derivation input ID.
        digest (str): Fresh independently computed digest.
        observed (int): Actual UTC observation time.
    """

    id: str
    digest: str
    observed: int


@frozen
class Query:
    """
    Select a read-only operation without embedding an executable check.

    Attributes:
        operation (Literal["find", "explain", "coverage", "preflight", "affected"]): Read-only facade operation.
        value (str): Literal query, assertion or canonical tool ID.
        view (Literal["both", "verified", "inferred"]): Explicit current projection.
        history (bool): Include qualified historical assertions.
        changed (tuple[str, ...]): Changed input IDs for reverse invalidation.
        required (tuple[str, ...]): Additional exact mandatory context IDs.
        observations (tuple[Observation, ...]): Independently supplied live input observations.
        action (str): Intended action label only; never executed.
    """

    operation: Literal["find", "explain", "coverage", "preflight", "affected"]
    value: str = ""
    view: Literal["both", "verified", "inferred"] = "both"
    history: bool = False
    changed: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    observations: tuple[Observation, ...] = ()
    action: str = ""


@frozen
class Claim:
    """
    Label every discovered assertion without conflating coverage and authority.

    Attributes:
        assertion (Assertion): Exact scoped candidate, including known counterevidence.
        entrypoint (str): Canonical repertoire reference when bound; empty for ordinary source intent.
        projection (Literal["verified", "inferred"]): Qualified current projection.
        verification (Literal["unreviewed", "supported", "disputed", "refuted", "withdrawn"]): Latest explicit review outcome.
        freshness (Literal["current", "stale", "unknown"]): Current declared-input validity.
        coverage (tuple[str, ...]): Applicable exact read receipts.
        conformance (Literal["unknown"]): Tests and declarations do not prove universal conformance.
    """

    assertion: Assertion
    entrypoint: str
    projection: Literal["verified", "inferred"]
    verification: Literal["unreviewed", "supported", "disputed", "refuted", "withdrawn"]
    freshness: Literal["current", "stale", "unknown"]
    coverage: tuple[str, ...]
    conformance: Literal["unknown"] = "unknown"


@frozen
class Result:
    """
    Report discovery completeness independently of readiness and action authority.

    Attributes:
        result (Literal["complete", "incomplete", "blocked"]): Discovery completeness only.
        scope (Scope | None): Admitted scope; omitted in opaque blocked responses.
        claims (tuple[Claim, ...]): Individually qualified code-intent assertions and optional capability bindings.
        witnesses (tuple[str, ...]): Complete selected closure IDs.
        evidence (tuple[Evidence, ...]): Exact closure evidence including mandatory teachings and counterevidence.
        reviews (tuple[Review, ...]): Explicit semantic decisions in the closure.
        coverage (tuple[Coverage, ...]): Exact bounded coverage receipts.
        anchors (tuple[Anchor, ...]): Scoped source references.
        affected (tuple[str, ...]): Reverse transitive invalidation IDs.
        missing (tuple[str, ...]): Admitted missing checks; opaque when existence is not authorized.
        horizon (int | None): Earliest expiry among applicable input observations.
        readiness (Literal["not-evaluated", "blocked"]): Discovery never grants operational readiness.
        execution_authority (Literal["not-evaluated"]): External admission is independently required.
        limitations (tuple[str, ...]): Mandatory uncertainty disclosures.
        query_version (Literal["intent-query/1"]): Deterministic query contract.
        generation (str): Exact native intent revision for conditional mutation.
        limits (Limits | None): Applied query budgets.
        output_bytes (int): Exact compact JSON response size, including this field.
    """

    result: Literal["complete", "incomplete", "blocked"]
    scope: Scope | None
    claims: tuple[Claim, ...] = ()
    witnesses: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    reviews: tuple[Review, ...] = ()
    coverage: tuple[Coverage, ...] = ()
    anchors: tuple[Anchor, ...] = ()
    affected: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    horizon: int | None = None
    readiness: Literal["not-evaluated", "blocked"] = "not-evaluated"
    execution_authority: Literal["not-evaluated"] = "not-evaluated"
    limitations: tuple[str, ...] = ("semantic-adequacy-requires-review", "dynamic-edges-may-be-unknown", "no-execution-authority")
    query_version: Literal["intent-query/1"] = "intent-query/1"

    generation: str = ""
    limits: Limits | None = None
    output_bytes: int = 0
