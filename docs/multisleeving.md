# Multisleeving

Multisleeving is running independent instances of one curated identity, borrowing
Altered Carbon's term for concurrent embodiments. Each instance starts from a
specific remote revision, works in its own Git worktree, and backs up to its own
`sleeves/<label>-<unique-id>` branch. Before normal session closure, its changes
must be integrated into the shared branch, normally `main`.

This is a workflow and a CLI gate. It cannot prevent a user from closing an agent
window or a host from killing a process. The supervised mode handles catchable
termination; remote checkpoints and durable storage cover interrupted sessions.

## Start and work

Use the version from this checkout until the next package release. Requires Git,
a configured commit-signing key, and authenticated `gh` access to the existing
private GitHub repository. Encrypted collections also need their existing key
backup, OpenSSL, and Cosign. No repository, credential, or signing key is created.

First commit any existing work in the primary checkout. Then start each instance
with a different external directory:

```bash
witful sleeve start --repo /work/identity --directory /work/sleeves/review --name review --key-dir /secure/collection-keys
```

Omit `--key-dir` for an existing private collection whose sources are directly
tracked in Git. `--base` and `--remote` default to `main` and `origin`. Startup
verifies that fetch and push target the same private GitHub repository, fetches
the integration head, creates a worktree, and pushes its branch. It never switches
or resets the primary checkout. Use non-sensitive labels and commit summaries.

The returned receipt identifies `worktree` and `directory`. For encrypted
collections, run Witful commands against `<directory>/source`. Startup restores
that revision into a separate owner-only plaintext directory outside the Git
worktree. Do not continue modifying the installer's shared collection from this
session. For directly tracked collections, work in `<directory>/checkout`.

Checkpoint after each coherent durable update, before expensive work, and before
a handoff. In an encrypted sleeve:

```bash
witful sleeve checkpoint --repo /work/sleeves/review/checkout --message 'Record reviewed observations'
```

The command validates, encrypts, and signs the isolated sources, then stages only
the three source transport files and signs/pushes the Git commit. It never stages
plaintext. For a directly tracked collection, select named paths with `--paths`;
for example, `--paths lessons.jsonl knowledge/applications.jsonl`. Existing staging
outside those paths blocks the checkpoint without altering the index. Repository
commit hooks and signing failures remain visible.

## Reconcile before closing

```bash
witful sleeve finish --repo /work/sleeves/review/checkout
witful sleeve guard --repo /work/sleeves/review/checkout
```

`finish` requires clean Git state and no uncheckpointed encrypted-source edits.
It fetches the latest integration head, merges into the isolated sleeve, validates
collection contracts, backs up the merged branch, and attempts a normal push to
`main`. It records closure only after fetching the remote and confirming that
main contains the sleeve's commits. Direct merge is the default. Main CI then
refreshes the collection figures using the existing pipeline.

Concurrent remote writes produce a normal non-fast-forward rejection. Retry
`finish` to fetch and reconcile again. Local lifecycle commands are serialized
across worktrees; remote Git ancestry is the cross-machine concurrency boundary.
Nothing force-pushes, deletes branches, weakens required checks, or rewrites the
primary worktree. Closed sleeves reject subsequent checkpoints; create a new one.

If branch protection requires a PR, use `finish --pull-request`. It creates or
reuses a PR and returns nonzero until it has merged. Use a **merge commit**, not a
squash or rebase merge, so both original histories remain verifiable. Rerun
`finish` after merge. Opening a PR or passing local validation is not closure.

`guard` exits nonzero while reconciliation is incomplete or new work exists.
An agent's ordinary shutdown routine must invoke it and report an unresolved
blocker rather than declaring the identity synchronized. Hosts that support exit
hooks can call it, but this package does not install undocumented client hooks.

## Conflicts and causal records

Two valid individual histories are not necessarily a valid combined history.
Conflicting instructions, catalog changes, and competing supersessions require a
reviewed choice. Hash-chained Life and checkpoint journals cannot be joined by
concatenating lines or rewriting stored hashes. Git conflicts and source-contract
failures leave the sleeve open. No automatic ours/theirs or union merge is used.

For an encrypted conflict, retain both signed branch snapshots. Restore each into
separate private directories with `witful collection restore`, using detached
worktrees at the corresponding commits as the `--checkout` inputs. Reconcile the
plaintext sources deliberately, validate them, and seal the accepted result in
the sleeve. Stage its matching ciphertext, signature, and checksum together.
Never edit encrypted JSON or choose a signature independently of its ciphertext.

Where histories require replay, use the normal recording commands on the current
accepted journal and retain references to the original branch/event as evidence.
Do not falsify earlier timestamps or silently discard competing teachings. Commit
the reviewed merge, checkpoint the reconciled local source, and retry `finish`.
The original signed branch commits retain the divergent evidence.

## Supervised execution and termination

For a noninteractive workload the user has authorized, wrap its executable directly.
Interactive agent sessions use the start/checkpoint/finish flow above:

```bash
witful sleeve run --repo /work/sleeves/review/checkout --shutdown-seconds 90 --stop-seconds 10 -- agent-command
```

For directly tracked sources, add named `--paths` before `--`. The workload runs
in the isolated checkout and receives `WITFUL_SLEEVE_WORKTREE` and
`WITFUL_SLEEVE_SOURCE`. Its agent instructions must use these paths rather than a
shared Codex home collection. The supervisor does not copy credentials or replace
client configuration. Only one supervised workload can own a sleeve locally.

On normal exit, `SIGTERM`, `SIGINT`, or `SIGHUP`, the lifecycle is:

1. Forward the first signal to the workload's process group and allow it to stop
   accepting work, flush records, and join its children/threads.
2. Bound draining by `--stop-seconds`; terminate remaining owned processes before
   taking the final snapshot. Workloads must not detach background writers.
3. Attempt the signed checkpoint and branch push before attempting integration.
4. Run `finish` within the remaining shared `--shutdown-seconds` budget. Repeated
   signals never extend that budget. Conflicts or failed checks leave the sleeve open.

A failed checkpoint still attempts to push already committed work with `backup`.
Incomplete edits stay on the durable filesystem. A stalled cleanup subprocess is
terminated and reaped when its remaining budget expires. Workload output is
inherited; the workload remains responsible for redacting its own logs. Cleanup
diagnostics omit raw Git output and source values.

Successful reconciliation preserves the workload's exit status, or `128 + signal`
for an interrupted run. Incomplete reconciliation returns 2. A failed application
is not reported as successful merely because its identity was saved.

## Pods, spot instances, and recovery

Run Tini as PID 1 and the supervisor beneath it. The image entrypoint uses Tini;
custom agent images also need Git, `gh`, signing tools, and any collection crypto
tools. The existing Helm chart is a read-only database-sync worker, not an agent
launcher. Do not give that worker identity-write credentials to make it a sleeve.

For an agent Pod, allocate a termination grace period larger than the supervisor's
shutdown budget, for example 120 seconds around a 90-second budget. Mount the
primary Git common directory and each sleeve's directory on durable volumes at
stable paths; linked worktrees refer back to that common directory. Mount keys
separately with restricted access. Use encrypted storage and backups for local
plaintext, and never substitute a shared writable source tree for isolated sleeves.

Kubernetes normally sends TERM before forced termination, but its grace period
includes a `preStop` hook. Avoid spending the backup window in a sleeping hook.
[Tini signal forwarding](https://github.com/krallin/tini#process-group-killing),
[Kubernetes termination flow](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-termination-flow).

`SIGKILL`, OOM termination, sudden node loss, and an expired spot notice cannot
execute cleanup. No merge-on-exit design prevents that loss. The recovery point
is the last successful remote checkpoint, supplemented by any surviving durable
volume. A shorter checkpoint cadence reduces the amount of unbacked work; it does
not guarantee that incomplete in-memory observations have been stored.

After an interrupted run:

- Inspect `witful sleeve status --repo /work/identity` for local open receipts.
- Preserve the volume, inspect `git status` in the sleeve, and verify no process
  still owns it. Never delete Git lockfiles while a writer is active.
- Use `witful sleeve backup --repo WORKTREE` to push existing commits when current
  edits cannot yet validate. Repair/review the records, checkpoint, then finish.
- If local storage was lost, fetch the remote `sleeves/*` branch into a new private
  checkout and recover its signed encrypted sources using the original key backup.
  Manually reconcile that preserved branch through the repository's normal merge
  process. Lost uncommitted or unpushed work cannot be reconstructed by the CLI.

Receipts under Git's common directory record branch, creation revision/time,
local paths, last encrypted-source digest, and verified closure. They are local
metadata, not replicated session state or public audit records. Back up that
common directory if local recovery receipts are required. Worktrees and remote
branches are retained after closure; cleanup is explicit.
