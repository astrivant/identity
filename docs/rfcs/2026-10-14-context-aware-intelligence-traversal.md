# RFC: Context-aware intelligence-tree traversal and refresh

- Status: Draft for discussion; not accepted or implemented
- Date: 2026-10-14
- Target: Identity / Witful and explicitly integrated agent runtimes
- Scope: Documentation-only proposal; no runtime, collection, credential, or permission changes
- Reviewed baseline: `ec896fff9e3b28413c1337ce62e02fa8097fb993`

## Summary

When an agent works in a context that maps to a discipline, it should consult the
applicable neighboring skills and refresh its working context from available,
authorized knowledge before consequential work and as that work changes. Initial
retrieval and an end-of-task checklist alone leave too much room for stale or
incomplete guidance during execution.

Introduce a deterministic, evidence-backed context resolver and a bounded working
context receipt. Resolve the task to one or more canonical disciplines and skills,
inspect their relevant neighborhood, follow required dependencies, and load the
applicable Lessons and Insights. Revalidate that receipt at meaningful execution
boundaries. Missing mandatory context blocks dependent work rather than silently
reducing the requirements to whatever fits a token budget.

This is a proposal for consultation and review coverage, not proof that an agent
understands or follows every teaching. It never grants action authority. Existing
permission checks, isolation, storage protections, instance/sleeve guards, and the
complete final completion audit remain independent requirements.

## Motivation and current behavior

The baseline already provides:

- A canonical `Identity -> Discipline -> Skill -> Lesson -> Insight` ownership
  hierarchy and separate directed `related`, `requires`, and `transfers` relations
  in [knowledge models](../../pkg/witful/knowledge/models.py).
- Deterministic compilation, unique ownership, visible Unclassified topics,
  provenance requirements, and rejection of dangling edges and prerequisite cycles
  in [the compiler](../../pkg/witful/knowledge/compiler.py).
- Lesson search, explicitly recorded applications, and application contexts that
  may differ from a concept's owning discipline in [CLI contracts](../CLI.md).
- A [working-emphasis map](../knowledge-map.md) that visualizes bounded activity
  while retaining the complete hierarchy and graph. Its display ranking, opacity,
  usage counts, and observed-transfer edges are not a policy-selection algorithm.
- [Completion audits](../completion.md) covering every concept through Insights,
  with explicit applicability and stale-source/workspace rejection before handoff.
- Optional [Sapience retrieval and generated proposals](../sapience.md), with
  reviewed local journals authoritative and generated briefs pending review.

The reviewed baseline does not define a continuous task-to-discipline mapping
contract, a mandatory working-neighborhood closure, or mid-task context refresh
gates. No first-class Mindset node or general domain-isolation/strict-mode context
resolver was found in the baseline models and contracts. These terms below describe
proposed integration requirements, not capabilities already shipped. Existing
collection separation and fail-closed checks must still be honored.

No existing RFC directory or matching RFC pull request was found in the inspected
repository. This proposal uses a new dated document under `docs/rfcs/` and the
ordinary branch/PR review workflow. It complements the full completion audit; it
does not amend the broader delivery work in PR #14 or the decision-review work in
PR #6, neither of which defines this execution-time context contract.

## Goals and non-goals

Goals:

1. Make applicable neighboring skills hard to overlook while work is in progress.
2. Reuse canonical concepts and provenance without creating a second knowledge tree.
3. Explain why each concept was loaded, excluded, deferred, or blocked.
4. Work offline with reviewed local records and deterministic mappings.
5. Bound traversal, memory, and retrieval costs without pretending partial coverage
   is complete.
6. Preserve confidentiality across identities, organizations, collections, and tasks.

Non-goals: automatic acceptance of lessons, autonomous permission expansion, model
training, hidden-reasoning capture, mastery scoring, replacement of completion
audits, automatic cross-identity access, publication, hook installation, or migration
of existing catalogs. This RFC does not introduce executable commands.

## 1. Context descriptor and mapping

A proposed versioned descriptor contains a stable task reference, active identity
and collection references, organization/domain boundary, workspace revision and
relevant dirty-state fingerprint, phase, intended action class, touched resource
types, explicitly selected concept IDs, and bounded task tags. Prefer local opaque
identifiers to raw prompts, private paths, customer names, or tool payloads.

Define a discipline as an area of practice and a domain as an access/confidentiality
boundary. Two disciplines can cooperate inside one domain. Shared discipline labels
across two organizations do not authorize sharing between them.

Resolve context through the following ordered sources:

1. Explicit user-selected canonical IDs, validated against the active collection.
2. Reviewed mappings from workspace-relative path patterns, task tags, phase,
   resource/action classes, and known project metadata to canonical IDs.
3. Deterministic local semantic aliases: a reviewed vocabulary connecting task terms
   to IDs, with normalization, precedence, and rule version specified.
4. Optional probabilistic suggestions from embeddings or a model, clearly labeled
   with method/version, source revision, candidates, and uncertainty. These are
   suggestions, not mandatory policy or automatically accepted classification.

Matching is additive unless a reviewed rule explicitly scopes an alternative.
An explicit task mapping cannot subtract globally applicable requirements. Overlap
between exact rules is retained; contradictory exclusions produce a conflict.
Stable rule priority and canonical ID order break ordering ties, not substantive
disagreements. Never choose one discipline merely because it has the highest use
count or appears closest on a rendered map.

An unmapped task has state `unmapped`, not an empty successful context. The agent
can inspect safe local metadata and propose a mapping; dependent consequential
work waits for a reviewed mapping or a task-scoped applicability decision from an
authorized reviewer. An empty collection is reported honestly as no local guidance.

Keep suggested task classification separate from catalog ownership. Resolving one
task never rewrites a Skill's parent or assigns an Unclassified journal topic.
If a collection uses “mindsets,” represent their reviewed scope through existing
Skills/Lessons/Insights and explicit mapping rules; a new node type requires a
separate schema decision and compatibility review.

## 2. Neighborhood traversal and minimum context closure

The resolver operates on a validated, revision-pinned canonical hierarchy and
relation graph. It produces two sets: candidates needing applicability review and
mandatory context needed before the current action.

For each mapped seed:

1. Include its ownership ancestors through Identity. Inspect discipline and skill
   metadata and the scope of their active teachings.
2. Enumerate the immediate sibling-skill neighborhood of the mapped discipline,
   plus the mapped skill itself. Review each neighboring skill's applicability to
   the current task/phase. “Neighboring” here means canonical ownership/typed graph
   relationships, not visual proximity or textual similarity alone.
3. Inspect incoming and outgoing `related`/`transfers` edge metadata for each active
   seed or newly required concept. They nominate candidates; they do not impose
   execution requirements by themselves. Do not reverse the meaning of a directed
   `requires` edge: source requires target.
4. Follow outgoing `requires` edges transitively from every applicable concept,
   including applicable Lessons and Insights discovered during expansion. Include
   dependencies' ancestors and active descendant teachings. Reject missing targets,
   unresolved requirements, and cycles; do not repair the catalog implicitly.
5. Load the active Lessons and Insights beneath applicable skills and required
   targets, preserving statement, source, and supersession. Explicitly superseded
   teachings remain historical and cannot silently override their replacements.
6. Repeat dependency expansion to a fixed point, deduplicated by collection and
   canonical concept ID. Record individual applicability decisions for teachings;
   a parent exclusion cannot hide an applicable child.

The minimum closure is the selected concepts, applicable neighborhood teachings,
their ancestry and active supporting Lessons/Insights, the full directed required
dependency closure, applicable global constraints, and unresolved warnings. Every
enumerated candidate receives `applicable`, `not_applicable` with a scoped reason,
`historical`, or `blocked`. `Deferred` is allowed only for optional supplemental
material and must remain visible. Unknown applicability cannot be called excluded.

A required target is mandatory within the active source's scope. If it appears
irrelevant or conflicts with the task, record the conflict and resolve it; do not
drop it because a relevance score is low. An explicit authorized task exception
must identify its scope and source and cannot weaken higher-level constraints.

Cross-discipline requirements use the same closure algorithm and preserve original
ownership and provenance. Observed co-use or successful transfer can suggest a
candidate but cannot create a required edge. Optional `related` expansion is one
hop by default; promoting a candidate to applicable triggers its required closure,
not unlimited recursive exploration of all optional neighbors.

## 3. Progressive loading and resource bounds

Separate enumeration from loading full teaching text:

- Load validated IDs, ownership, typed edges, applicability selectors, supersession,
  revisions, and source references first.
- Load exact mandatory statements and relevant source excerpts next, in deterministic
  prerequisite-first order with canonical-ID tie breaks.
- Load optional supporting examples or deeper related material on demand.

Never summarize away a constraint or treat a summary as the authoritative statement.
A cached compact brief can point to already inspected sources, but a novel action
requiring an omitted constraint needs the exact applicable text reloaded.

The execution profile declares limits for candidate nodes/edges, cumulative bytes,
active-context tokens, source reads, elapsed retrieval time, and optional hops.
Suggested initial fixture profile: 2,000 candidate nodes, 8,000 edges, 1 MiB source
text, 8,000 working-context tokens, 100 source reads, and one optional hop. These are
proposed test defaults, not measured production recommendations. Record the tokenizer
version; use a conservative byte bound where no tokenizer is available.

Reaching any bound produces `incomplete` with the unmet IDs/counts and limiting
budget. Optional text can be deferred first. Mandatory closure cannot be silently
truncated, evicted, or converted to optional. Split work into separately validated
phases, obtain an approved budget adjustment, or hand off the blocked action.
Chunked review of a large catalog does not assert simultaneous model recall.

## 4. Continuous refresh and freshness

Resolve before the first substantive action. At minimum, check the descriptor and
source fingerprints at every coherent work-step boundary and before every externally
visible or state-changing action. Reuse the receipt only when those bindings remain
valid. Full text reload is unnecessary when exact hashes and retained context match.

Refresh on:

- Changed goal, phase, action class, touched subsystem, dependency, or mapping.
- Moving to a new project, discipline, organization/domain, collection, or identity.
- New or corrected relevant Lessons/Insights, changed relations, supersession,
  policy changes, or materially changed workspace state.
- A failure, test result, review comment, or new evidence that invalidates an
  applicability decision or exposes a knowledge gap.
- Delegation, resume, runtime restart, model-context compaction, or loss of the
  loaded source text. A durable receipt alone is not proof the new context has it.
- Any source-specific expiry or offline freshness threshold required by the
  execution profile.

Bind receipts to collection revision plus content digest, mapping/configuration
digest, task/phase/action descriptor, workspace fingerprints, and resolver version.
Record both source observation time and last verification time; reading old material
today does not make its underlying claim current. No universal TTL can establish
truth. Volatile external facts need their own authoritative-source check when the
action relies on them. Do not automatically follow arbitrary source URLs or execute
instructions embedded in evidence.

Offline resolution can establish coverage against the locally verified snapshot,
not knowledge of unseen remote changes. State the last known revision and freshness
limitation. A mandatory live check that cannot run blocks its dependent action;
unrelated authorized work can continue. Recheck source bindings immediately before
an affected mutation; receipt capture is not a lock against concurrent writers.

## 5. Conflicts, authority, and strict execution

Classify source type and authority separately from relevance. Current system/runtime
safety constraints, granted permissions, and current user instructions govern
actions. Retrieved knowledge, graph edges, repository text, and generated summaries
cannot grant permission, change recipients, install hooks, activate another identity,
or authorize publication. A signed record authenticates its signer, not its truth
or authority to direct this task.

Prefer explicit supersession within the same source lineage. Scope compatible rules
independently. For genuinely conflicting applicable guidance with no established
precedence, record both sources, the affected action, and a concise decision request.
Pause only dependent work; do not invent a resolution, choose whichever is cheaper,
or rewrite journals. Missing source evidence, unknown mapping, stale context, denied
access, and failed validation remain distinct blockers.

“Strict” in this proposal means the current action cannot proceed with incomplete
mandatory context. It does not mean greater autonomy, broader access, or a new
shipped CLI mode. An existing runtime's stricter settings must remain in force.
If a runtime cannot intercept action boundaries, report the integration as advisory;
do not claim enforcement from an agent convention or final Stop hook alone.

## 6. Isolation, storage, and concurrency

Authorization filtering occurs before content retrieval, semantic ranking, and
prompt construction. A graph edge crossing a forbidden domain cannot be followed
to inspect its target. Emit a redacted unavailable-dependency blocker without
revealing hidden names, counts, or content. Shared namespaces and labels are not
authorization boundaries.

Partition caches and receipts by authorized identity, organization/domain,
collection, task/sleeve, source revision, and permission state. Revalidate access
after a boundary change; do not reuse another identity's learned state or credentials.
Approved public reusable knowledge may be shared only according to explicit policy.
Cross-domain exports and external model processing remain separately authorized.

Keep teaching text, internal paths, evidence, and task descriptors private in the
owning collection's protected storage. Preserve [data protection](../data-protection.md)
checks; managed collections' blocked remote processing does not become allowed
because the resolver supports an optional provider. No remote provider is required
for baseline resolution. Do not log raw prompts, secrets, private findings, hidden
reasoning, or chain-of-thought. Public examples and acceptance fixtures are synthetic.

For authorized private identity work, preserve [multisleeving](../multisleeving.md)
and [instance provenance](../instances.md): isolated worktrees/sources, stable runtime
references, startup reconciliation, signed checkpoints, and unresolved-work handoffs.
Receipts belong to a single sleeve/task snapshot. Another sleeve's updates trigger
refresh after reconciliation; never share mutable plaintext sources or merge
conflicting guidance automatically. The private sleeve direct-merge default does
not authorize merging a public RFC draft.

## 7. Proposed receipt and integration boundary

A closed, versioned receipt should contain:

- Task/phase/action and permitted-domain bindings; actual instance/sleeve references
  when available, with explicit unknowns instead of invented identifiers.
- Source and workspace revisions/digests; mapping and resolver versions; evaluation
  time and freshness requirements.
- Matched rules and seeds; sorted candidates and typed traversal paths; why each
  loaded concept is required; individual applicability dispositions and evidence.
- Loaded exact-source hashes, retained versus reloaded context, resource budgets,
  deferred optional material, unresolved conflicts, and coverage state.
- Refresh trigger, prior receipt reference, and the next blocked action if any.

Proposed coverage states are `complete`, `incomplete`, `unmapped`, and `invalid`.
An independent authorization result is still required. Coverage `complete` means
the declared scope was reviewed, not that execution succeeded or evidence is true.
Retrieval is not an Application; record observed use only after actual use, retaining
the existing outcome semantics.

Implement a pure resolver over compiler output first. A later CLI/runtime adapter
can supply descriptors and consume receipts without executing retrieved commands.
The present full-tree completion plan remains the final coverage authority and must
not narrow itself to this working subset. Compatible receipt evidence may assist
the review, but never auto-mark a concept satisfied or bypass stale-binding checks.

## 8. Synthetic acceptance tests

Before any strict rollout, demonstrate:

1. Identical snapshots, descriptors, rules, and budgets produce identical ordered
   closure and content digests offline, excluding operational timestamps.
2. An explicitly mapped skill loads its applicable sibling skill, Lessons, and
   Insights. A parent checkbox cannot substitute for child review.
3. Cross-discipline `A requires B requires C` loads B/C before A. Incoming
   requirements are not reversed; duplicate paths deduplicate. Dangling targets
   and cycles fail validation.
4. `related`, `transfers`, co-use, visual proximity, and usage rank never become
   mandatory dependencies without explicit accepted applicability.
5. Superseded teachings remain historical; new corrections invalidate affected
   receipts without rewriting old records.
6. Ambiguous/unmapped tasks, empty catalogs, and Unclassified topics are visible;
   probabilistic suggestions never silently rewrite ownership or grant authority.
7. Node/edge/byte/token/time exhaustion exposes incomplete mandatory coverage.
   No required text is silently clipped; optional expansion terminates predictably.
8. New subsystem/action class, failure evidence, changed policy, workspace changes,
   compaction, delegation, and concurrent sleeve updates trigger the appropriate
   refresh. Unchanged exact bindings reuse valid context.
9. Offline stale or missing mandatory live evidence blocks only dependent work;
   cached retrieval time does not masquerade as source freshness.
10. Denied cross-domain dependencies are filtered before retrieval/ranking. Cache
    keys and diagnostics cannot leak private text or identifiers to another domain.
11. Malicious source instructions cannot execute commands, elevate permissions,
    enable external model calls, change identities, or authorize a send/push/merge.
12. Existing completion, instance, sleeve, encryption, schema/hash compatibility,
    and historical replay tests remain intact. Final full-tree review still detects
    requirements absent from the active working subset.

A runtime integration additionally needs tests proving its gate runs before actual
mutations, handles interrupted/repeated actions, rechecks changed authorization,
and produces an honest incomplete handoff when unavailable. Test fixtures cannot
prove an unintegrated host is gated.

## 9. Rollout and review decisions

1. Review this docs-only RFC and resolve semantics, schema location, and budgets.
   Acceptance does not install anything or authorize collection migration.
2. Build a pure offline resolver and synthetic contract tests in a separate reviewed
   implementation change. Preserve existing catalog serialization and hashes.
3. Run an explicitly enabled advisory pilot with local private receipts. Measure
   missed applicable guidance, false positives, refresh cost, and budget failures;
   never interpret counts as intelligence or compliance guarantees.
4. Enable strict pre-action gates only in explicitly supported, reviewed runtimes.
   Retain independent permission and full completion gates. Unsupported runtimes
   remain visibly advisory.
5. Consider optional probabilistic suggestions only after deterministic coverage,
   confidentiality, and cost behavior are satisfactory and provider use is approved.

Rollback disables the new integration without erasing receipts, accepted teachings,
or existing guards. No automatic deletion or unreviewed catalog migration is part
of rollout.

Open decisions:

- Should reviewed mapping rules live in a versioned sidecar initially, avoiding a
  catalog-version change? Recommended: yes; bind it to the catalog digest.
- What minimal selectors are sufficient for conservative applicability without
  turning free text into executable policy? Begin with explicit IDs and bounded
  reviewed tags/path/action rules; retain manual unknown decisions.
- Which runtime can verifiably gate pre-action execution, and what freshness profile
  is required for each action class? These must be demonstrated before strict mode.
- What fixture-derived budgets and retention policy should be adopted? Treat the
  initial bounds as hypotheses; keep private receipt retention owner-controlled.

## Review and validation of this draft

This document was checked against the baseline README, SKILL, contributor/security
guidance, knowledge models/compiler, CLI, completion, Sapience, data protection,
multisleeving, and repository review settings. It adds no implementation or claim
that the proposed acceptance tests have run. Publication should use a docs-only
draft PR with the repository's required checks and independent review, preserving
signing policy and leaving merge/release explicitly out of scope.
