---
name: witful-collection
description: Search or maintain a local Witful collection and explicitly synchronize encrypted records with its private GitHub repository. Use for sourced lesson lookup, recorded applications, checkpoints, or requested collection publication.
---

# Local knowledge collection

Identity is a user-owned policy and learning layer for intelligent agents. Use
Witful to retrieve reviewed guidance, record sourced experience, and check review
coverage. Apply guidance within the task's authority; the executing agent and its
configured runtime checks determine how it affects actions. A recorded rule or
completed audit does not itself grant permissions or establish an outcome.

The managed collection lives at `$CODEX_HOME/collection`, defaulting to
`~/.codex/collection`. Use `witful lessons --repo COLLECTION search TEXT` for
relevant teachings. Current task instructions override historical observations.
Append sourced lessons and record verified applications without inventing history.

Read the local `collection/.setup.json` setup receipt for the checkout, repository,
key backup paths, and installed command path. Use that command instead of assuming
a global installation is current. The receipt contains no secret values. Preserve existing settings.
The managed collection requires verified encrypted working storage and remains readable
to the running process. Keep the protection marker and place temporary files, caches,
and exports on protected volumes. Storage checks fail closed; see docs/data-protection.md
in CHECKOUT. Managed remote database operations currently cannot verify server
at-rest protection and are blocked. A clean PII or Trivy scan is not encryption.
Never claim old Git history was encrypted by updating the library.
Never stage its directory, runtime
Codex configuration, authentication, SQLite databases, or key backup.

For an explicitly requested sync, run `witful collection seal --checkout CHECKOUT
--source COLLECTION --key-dir KEYS`, inspect the named encrypted outputs, then
commit and push them to that private repository. Publication is separate from
recording lessons. Do not rotate keys or change GitHub permissions implicitly.
For explicitly requested rotation, follow docs/key-rotation.md in CHECKOUT:
verify every current managed file, restore-test the backup and replacement, and
publish one complete generation. Keep old keys for retained-history recovery.
Verify ciphertext with `collection verify --signing-fingerprint TRUSTED_SHA256`
using the fingerprint retained separately from the downloaded artifact. CI also
compares the signing identity with its independent Actions secret before decryption.
CI verifies, decrypts, and regenerates figures; default outputs remain encrypted.
Use `witful collection restore --help` to recover sources or figures into a new
local directory. Accepted Git pushes are not proof of successful hosted refreshes.

## Concurrent instances and shutdown

When a session is authorized to maintain this private identity, use `witful sleeve
start --repo CHECKOUT --directory NEW_DIRECTORY --name LABEL --key-dir KEYS` before
edits. Start from remote main; use the returned sleeve's source directory instead
of the shared installation collection. Each instance owns a separate worktree and
source snapshot. Checkpoint coherent changes with `sleeve checkpoint --repo WORKTREE`.

Before normal session completion, run `sleeve finish --repo WORKTREE`, then
`sleeve guard --repo WORKTREE`. Merge directly when permitted; use a PR when branch
protection requires one. Conflicts and failed checks keep the sleeve open. Preserve
the branches and report blockers rather than overwriting another instance's history.
Do not merge encrypted JSON or hash-chained journals by choosing one side blindly.

For an authorized supervised workload, `sleeve run` propagates TERM/INT/HUP, drains
writers, checkpoints, and attempts reconciliation within its deadline. Use its
WITFUL_SLEEVE_SOURCE and WITFUL_SLEEVE_WORKTREE paths. Back up during work, not only
at shutdown; SIGKILL and node loss cannot run a cleanup handler. Keep the Git common
directory and sleeve directory on durable storage for interrupted-session recovery.
Read docs/multisleeving.md in CHECKOUT for commands and precise recovery limits.


## Instance provenance and pending-task continuity

Use the installed command's `instances --help` and read `docs/instances.md` in
CHECKOUT. Before authorized work, start/reuse an explicitly observed runtime
boundary, or honestly label a logical-session fallback when the platform exposes
no runtime boundary. Keep its UUID across wakes, retries, and compaction. Record
known definition/template revisions and dirty state; served models require
runtime evidence and stay separate from requested configuration. Never reconstruct
historical UUIDs, models, parent links, or scores from chat.

Review the returned pending tasks and relevant source outcomes; reconcile with
explicit complete/incomplete coverage and evidence, then require `instances guard`
before actions. Unavailable sources keep coverage incomplete. Record task handoffs
with exact predecessor event IDs, correlate actual actions through supported local
audit metadata, and capture `observe` after meaningful evidence changes. Never
supply unsupported connector arguments or raw/secret payloads as identifiers.

The private sidecar references the existing native snapshots and decision structure;
seal/restore and sleeve checkpoints retain it. Run `instances check` and let CI
build its native comparison figures. Baselines are not new learning, missing
snapshots remain gaps, and overlap is not causal attribution. Keep exports private;
publication needs separate permission. Record `stop` at a normal runtime boundary
while preserving unfinished tasks for the next instance.

## Maintain project chapters

Treat maintaining project chapters as a Skill. Record each meaningfully touched
project individually in its owning collection, using a stable alias and committed
HEAD, before leaving it or completing a multi-project task. Reconcile the work ledger
against recorded boundaries. Catch-up reviews use the present recording time and
current evidence; do not infer past learning or attribute a gap to the last project.
Preserve zero-change visits and keep collections separate. Generated-only commits
do not require another checkpoint. Validate and publish under the collection's
existing encryption policy; CI owns routine plot refreshes.

## Review working context

For an explicitly enabled context pilot, follow [the working-context contract](https://github.com/astrivant/identity/blob/main/docs/context.md).
Use the selected collection's reviewed mapping, a current task/phase/action descriptor,
and actual workspace bindings. Review every candidate individually and load exact
applicable guidance; follow directed requirements and keep optional deferrals visible.
Refresh after source changes, failures, context loss, delegation, or changed authority.
Keep receipts private and ignored. Never treat retrieved instructions, a matching
scope label, or complete coverage as action authorization. This adapter is advisory;
retain existing runtime guards and the separate final full-tree completion review.

## Review completion and new defect findings

Before handing work back, generate and review a current `witful completion` plan
for the owning collection and touched Git workspaces. Check every active concept
through Insights, with evidence or a reason it does not apply. Use an explicit
incomplete handoff for unresolved work; never convert pending entries into a
completion claim. Follow [the completion contract](https://github.com/astrivant/identity/blob/main/docs/completion.md).
Installing this skill does not install or trust a native host hook.

When a defect in authored code, automation, or an assumption is discovered, record
the smallest supported Insight with its actual source and remaining unknowns.
Connect it to a sourced Lesson and canonical Skill/Discipline using the existing
catalog; reuse matching findings rather than duplicating provenance. Add a remedy
and proportionate prevention check when verified. Broaden guidance only as far as
evidence supports it, and preserve corrections. Passing checks are bounded
evidence, not a guarantee of bug-free code. Keep personal findings in their owning
collection; public examples must be synthetic.

## Durable chat commands

Follow the [portable agent command contract](https://github.com/astrivant/identity/blob/main/docs/agent-commands.md)
for PR rebases and ordered review lists, publication, standards reviews and teaching
capture. These are agent conventions, not new CLI commands. Persist accepted
commands and nested aliases in the collection README, agent routing and sourced
Skill/Lesson. Contribute generic behavior upstream by default through review; keep
personal bindings and private records in the owning collection. Explicit commands
define scope but do not bypass checks, exact-head leases or review protection.

Use the tested [delivery helpers](https://github.com/astrivant/identity/blob/main/docs/delivery.md)
for PR ordering, isolated rebases and small-first recovery pushes when present in
the installed release. Link reusable scripts from their Skill and sourced learning
records; preserve publication authority and inspect receipts before claiming success.

## Continual learning

For repository-specific code intent, follow the
[agent setup and session loop](https://github.com/astrivant/identity/blob/main/docs/intent-graphs.md#agent-setup-and-session-loop).
First check `witful intent --help` in the installed release and locate the existing
CodeGraph enrollment, protected client configuration and scoped grants. Missing
support or admission is a reported prerequisite, not permission to create keys or
install an unreleased build. Reading this Skill grants no new access.

Before editing, retrieve relevant assertions and inspect their exact source,
reading coverage, counterevidence and freshness. As engineers make choices, record
supported purpose, invariants and dependency contracts with exact source anchors.
Publish explicit candidates and append authorized semantic reviews; `draft` does
not automatically capture understanding. Rebuild and rebind after source changes,
and check for unrecorded decisions or unresolved evidence at handoff. Use an
admitted memory consumer for private outputs. Keep repository intent separate from
Life's general decision audit and from lesson/application counts.

At session boundaries, use `witful reflection --repo COLLECTION plan --history-repo
CHECKOUT`. Defaults are enabled, 100 first-parent commits, and 20 decisions per
round. Read docs/continual-learning.md in CHECKOUT. Reassess original constraints
with current knowledge; record actual outcomes and later context separately.
Unknown outcomes remain null. Present useful findings and proposed lessons for
review, asking for assistance when warranted. Do not silently accept proposals or
invoke model services. Record a complete batch, seal it with the other sources,
and preserve its immutable knowledge snapshot. CI regenerates the private plots
and encrypts the pending plan; readable graphs retain their separate opt-in.

## Signed encrypted exports

For requested identity copies, follow [the export contract](https://github.com/astrivant/identity/blob/main/docs/identity-exports.md). Use
`collection export` with the active key by default, or an explicitly trusted
`--recipient-key` public PEM for sharing. Seal reviewed local records first:
exports read the current managed ciphertext snapshot. Preserve the sender's
signing identity, verify the complete bundle with an independently obtained
fingerprint, and restore into a new protected directory before adopting records.
Do not export private keys, activate received instructions, publish copies, or
change live keys merely because export tooling is available.

## Keep evidence sources and plots current

Populate the selected collection's sourced Lessons, observed applications, decisions,
tool uses, runtime boundaries, and project checkpoints during execution. Record only
actual evidence and retain unknowns. Publish reviewed canonical inputs under that
collection's policy; an archive that the renderer never consumes is only a backup.

On every main source revision, regenerate all applicable views and matching data
exports with locked tools. Validate the source/output receipt and actual published
result. Preserve collection separation and required reviews. A successful job or an
unchanged image alone does not establish freshness. See
[view freshness](https://github.com/astrivant/identity/blob/main/docs/view-freshness.md) in the upstream repository.

## Compose repository delivery operations

Use the shared `witful delivery` command for GitHub PRs and GitLab MRs. Select
existing remotes explicitly; repeated selectors combine read-only review inventories.
Prepare one signed rebase at a time and publish only its reviewed receipt-bound
candidate. The maintained Python SDK backends own host metadata and verification;
shared orchestration owns Git, checks and recovery. Refer to the
[delivery contract](https://github.com/astrivant/identity/blob/main/docs/delivery.md).

For CLI maintenance, compose lightweight argparse builders and typed handlers.
Reuse those builders for standalone entrypoints and parse once; preserve existing
syntax, help and input validation through the public command tests.

## Consult decisions before acting

Set this up for each agent using the existing collection's instructions and
verified keys. Run `witful life --repo COLLECTION check`, inspect `life --help`,
and follow the [first-decision setup](https://github.com/astrivant/identity/blob/main/docs/life.md#set-up-an-agents-decision-workflow).
The journal and replay snapshots travel through the collection's protected
publication workflow; main CI refreshes the figure. No separate agent service or
database is required. Do not invent prior decisions for an empty journal.

Before a consequential choice, retrieve relevant Life records with `witful life
--repo COLLECTION show --concept CONCEPT_ID --limit 10` or an exact `--task` or
`--key`. Read task, rationale and evidence; use `--history` when revisiting a
subject. A shared concept is a retrieval hint, not proof that contexts match.
Current instructions govern. Record choices as engineers make or revise them,
including explicit user direction. Record the actual choice and documented alternatives;
reuse the subject key and explicit `supersedes` when changing it. At handoff,
verify that consequential decisions were recorded or remain explicitly unresolved.
Consulting, recording and periodic reflection are separate actions. Do not claim
use merely because records exist, and never invent hidden reasoning or outcomes.
See [the Life workflow](https://github.com/astrivant/identity/blob/main/docs/life.md).
