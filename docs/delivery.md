# Reusable delivery helpers

`witful delivery` turns repeated PR ordering, rebase preparation, and recovery
pushes into tested operations. It uses the existing authenticated GitHub CLI and
Git installation. No new service credentials are created. The implementation is
[`pkg/witful/delivery`](../pkg/witful/delivery/); tests use real local Git remotes
and SSH-signed commits with synthetic GitHub responses.

The helpers are available from this source revision; consumers pinned to an older
Witful release need a reviewed source installation or an explicitly recorded,
licensed copy until the next release. Do not silently change a consumer's pin.

## Inputs and prerequisites

| Input | Meaning |
| --- | --- |
| `--repo PATH` | Existing checkout; defaults to the current directory. Origin must have one matching, credential-free GitHub fetch/push URL. |
| `--dependencies FILE` | Optional reviewed extra PR prerequisites, such as `{"12": [6]}`. Branch bases are inferred automatically. |
| `--old-base SHA` | Original replay boundary recorded before changing the parent branch. Resolve it in the source checkout. |
| `--worktree PATH` | New isolated worktree path. Existing worktrees and the caller's index are preserved. |
| `--receipt FILE` | Private local JSON state outside the candidate worktree. Keep receipts ignored and retain them until reconciliation. |
| `--checks FILE` | JSON object of literal command vectors, for example `{"commands": [["pytest", "-n", "2", "pkg/witful"]]}`. |
| `--reviewed-head SHA` | Exact candidate commit inspected before PR publication. |
| `--spec FILE` | Recovery source, published base branch, new `recovery/` branch, and selected coherent file groups. |

Activate the project's locked environment before starting. Child checks inherit
its `PATH` and `VIRTUAL_ENV`; the helper removes inherited Git index/worktree
selectors so they cannot affect isolated candidates. Git author and committer must
be configured, `commit.gpgsign` and `tag.gpgsign` must be enabled, and
`user.signingkey` must identify the owner's registered key. Local verification must
work too; SSH signing requires the appropriate allowed-signers configuration.

Inspect PR notes/reviews, publication authority, privacy requirements and branch CI
triggers before mutation. Reading a Skill or a plan does not authorize publication.
The `apply` and `publish` subcommands are explicit mutations. Helpers never merge,
release, retarget PRs, weaken checks, or resolve semantic conflicts automatically.

## Review and rebase PRs

```bash
witful delivery --repo . pr show
witful delivery --repo . pr show --json > /tmp/pr-inventory.json
```

Review prerequisites first. Ready independent PRs sort by changed lines, changed
file count, then PR number. Binary transfer size is a separate concern. JSON keeps
the PR body, exact head/base SHAs, raw check evidence and review state. Read review
threads separately when intent is unclear; an arbitrary PR mention is not inferred
as a dependency. The bounded inventory refuses a potentially truncated 1,000-PR
result. Fork PRs can appear in review order but mutation supports same-repository
feature branches only.

Capture original heads and replay boundaries **before** rewriting any parent.
For a main-based PR, use the original merge base. For a stacked child, use the
original parent head when it is an ancestor; inspect divergent stacks explicitly.
Process each prerequisite through review/publication before preparing its child:

```bash
witful delivery --repo . pr rebase --number 5 --old-base ORIGINAL_BASE_SHA \
    --worktree /tmp/pr-5-work --receipt /tmp/pr-5.json
```

The helper fetches the current intended base, resolves immutable endpoints, saves
a recovery ref and receipt, and performs a signed rebase in the new worktree.
Overlapping commits are reapplied; empty results stop for inspection. Conflicts
leave the worktree and receipt intact. Inspect both intentions, repair the source,
run focused checks and finish with `git rebase --continue` in that worktree. Do not
blindly skip commits or choose one side globally.

Inspect `git range-diff OLD_BASE..ORIGINAL_HEAD NEW_BASE..CANDIDATE_HEAD`, source
changes and signatures. Receipts contain those endpoints. Then publish the exact
reviewed SHA:

```bash
witful delivery pr publish --receipt /tmp/pr-5.json \
    --reviewed-head CANDIDATE_HEAD --checks /tmp/checks.json
```

Publication runs the supplied checks and all configured pre-commit hooks. Source
or HEAD drift, an unfinished rebase, a moved base, invalid signatures, or a changed
remote head blocks publication. Each rewritten commit is locally verified. The
push uses an explicit expected-head lease, then verifies remote readback and the
head's GitHub signature. Inspect hosted CI for that revision and update the PR's
intent/validation; remote publication does not mean CI passed. Independent PRs may
continue while another needs conflict resolution.

## Smallest-first recovery pushes

Git transfers reachable objects; staging files in size order does not control a
single pack's wire order. This helper creates independent accepted checkpoints.
Select a **committed** source snapshot, a baseline already published on the remote,
and a new branch whose CI effects are understood. The source snapshot may contain
an unsent large blob: it is retained locally, never made a parent of the recovery
commits. Existing source history is not rewritten.

Create `/tmp/recovery-spec.json` with reviewed repository-relative paths:

```json
{
  "source": "SOURCE_COMMIT_SHA",
  "base_branch": "main",
  "branch": "recovery/small-first",
  "batches": [["docs/large-figure.png"], ["README.md"], ["schema.json", "schema-reader.py"]]
}
```

```bash
witful delivery --repo . recovery plan --spec /tmp/recovery-spec.json \
    --worktree /tmp/recovery-work --receipt /tmp/recovery.json
witful delivery recovery apply --receipt /tmp/recovery.json --checks /tmp/checks.json
```

Planning sorts groups by total source blob bytes, then literal paths. Use one file
per group for strict file-size ordering; keep dependent files in a coherent group.
Each intermediate tree must pass the selected checks and all configured hooks.
Plans reject unchanged, duplicate, escaping, absent, directory, symlink and
submodule selections. This first implementation handles regular added/modified
files, not deletions, renames as operations, LFS migrations, or artifact uploads.
Receipts explicitly list source changes omitted from the selection.

Applying creates signed commits from the published baseline and verifies each
remote checkpoint before appending the next. On a failed large upload, earlier
accepted commits remain usable. Repeat the same `apply` command: a pending commit
is reused, and readback handles a lost response after remote acceptance without
resending that commit. Another writer's remote changes stop recovery. A completed
receipt still requires fresh remote readback; it is not proof of current delivery.

Receipts are atomically replaced with owner-only permissions and locally locked.
After a killed process, inspect the worktree and process before removing a stale
lock. Interruptions between a local Git mutation and receipt persistence can need
manual reconciliation; the helper preserves that state and refuses to guess.
Hook modifications likewise require review, not automatic staging. Do not delete
a retained worktree or recovery ref until its work has been reconciled. Integrating
the resulting recovery branch follows ordinary PR review; selected-batch success
does not imply the entire source snapshot, hosted CI, or a release is complete.

## Reuse through the learning tree

A Skill should link directly to its tested helper and this contract, including the
command, expected inputs, mutation boundary and recovery behavior. Its sourced
Lesson and Insights should reference that artifact using the existing supported
reference fields. Consult the contract, execute the helper, and inspect its receipt;
load implementation details only when diagnosing or changing them. Record actual
applications with observed evidence. Do not treat installing a script as use or
claim measured token savings without measurement.

Authoritative contracts: [Git push and exact leases](https://git-scm.com/docs/git-push),
[Git rebase replay boundaries](https://git-scm.com/docs/git-rebase), and
[GitHub CLI PR metadata](https://cli.github.com/manual/gh_pr_list).
