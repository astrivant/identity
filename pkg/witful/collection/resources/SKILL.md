---
name: witful-collection
description: Search or maintain a local Witful collection and explicitly synchronize encrypted records with its private GitHub repository. Use for sourced lesson lookup, recorded applications, checkpoints, or requested collection publication.
---

# Local knowledge collection

The managed collection lives at `$CODEX_HOME/collection`, defaulting to
`~/.codex/collection`. Use `witful lessons --repo COLLECTION search TEXT` for
relevant teachings. Current task instructions override historical observations.
Append sourced lessons and record verified applications without inventing history.

Read the local `collection/.setup.json` setup receipt for the checkout, repository,
key backup paths, and installed command path. Use that command instead of assuming
a global installation is current. The receipt contains no secret values. Preserve existing settings.
The collection is private plaintext locally; never stage its directory, runtime
Codex configuration, authentication, SQLite databases, or key backup.

For an explicitly requested sync, run `witful collection seal --checkout CHECKOUT
--source COLLECTION --key-dir KEYS`, inspect the named encrypted outputs, then
commit and push them to that private repository. Publication is separate from
recording lessons. Do not rotate keys or change GitHub permissions implicitly.
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
