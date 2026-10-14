# Reusable delivery helpers

`witful delivery` orders GitHub pull requests and GitLab merge requests, prepares
signed rebases, and resumes recovery pushes. It uses PyGithub and python-gitlab
for REST API operations, with Git for local history and transport. Existing token
variables or host-specific `gh` / `glab` logins supply authentication. The implementation is
[`pkg/witful/delivery`](../pkg/witful/delivery/); tests use real local Git remotes
and SSH-signed commits with synthetic responses parsed by both real SDKs.

The helpers are available from this source revision; consumers pinned to an older
Witful release need a reviewed source installation or an explicitly recorded,
licensed copy until the next release. Do not silently change a consumer's pin.

## Inputs and prerequisites

| Input | Meaning |
| --- | --- |
| `--repo PATH` | Existing checkout; defaults to the current directory. Each selected remote must have one matching, credential-free fetch/push URL. |
| `--remote [PROVIDER:]REMOTE` | Defaults to `origin`; repeat for combined read-only inventories. Self-managed hosts require `github:` or `gitlab:`. |
| `GH_TOKEN`, `GITHUB_TOKEN` | GitHub.com credentials, in that order; otherwise use the existing `gh auth token --hostname` login. |
| `GH_ENTERPRISE_TOKEN`, `GITHUB_ENTERPRISE_TOKEN` | GitHub Enterprise credentials, in that order, then its host-specific CLI login. |
| `GITLAB_TOKEN`, `GLAB_TOKEN` | GitLab credentials, in that order, then the existing `glab auth token --hostname` login. |
| `--dependencies FILE` | Reviewed PR/MR prerequisites. Numeric aliases require uniqueness; qualified keys also support dependencies across hosts. |
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

## Review and rebase pull or merge requests

```bash
witful delivery --repo . pr show
witful delivery --repo . --remote github:origin --remote gitlab:mirror pr show --json > /tmp/request-inventory.json
witful delivery --repo . --remote gitlab:mirror mr show
```

`pr` and `mr` are aliases for the same request operations. Select existing Git
remotes explicitly; neither alias filters a combined inventory. Hosted domains are
auto-detected, while self-managed HTTPS or standard SSH URLs require a provider
qualifier. GitLab subgroup paths are supported. API bases are GitHub.com, the
selected Enterprise host's `/api/v3`, or the selected GitLab host's `/api/v4`.
Custom SSH ports and installations under a URL path prefix are not supported.
Tokens are kept in memory and never written into receipts. Public read-only API
access can work without a token, subject to the host's rate and access limits.

Review prerequisites first. Ready independent requests sort by known changed-line
and file counts, project identity, then request number. Missing, capped or collapsed
GitLab diffs retain unknown counts and sort after measured independent work. Binary
transfer size is a separate concern. Branch-stack inference stays within each
provider project; it never joins similarly named branches across hosts.

JSON retains the request body, source and comparison SHAs, provider-labelled review
evidence and exact-source commit statuses. GitLab's `baseRefOid` is the diff's
recorded target SHA; preparation always fetches the live target branch. A merge-result
pipeline can have a different SHA and remains separately labelled. Review states
are advisory evidence, not a declaration that host approval rules or required checks
passed. Read review threads when intent is unclear; arbitrary mentions are not
inferred dependencies. Each SDK-managed inventory is capped below 1,000 entries,
including reviews and checks; any failed or capped provider aborts the combined
result rather than silently omitting work.

Qualified dependency keys have the form `github:github.com/owner/project#12` or
`gitlab:gitlab.com/group/subgroup/project#6`. Use those keys when numbers collide,
for example `{"github:github.com/owner/project#12": ["gitlab:gitlab.com/group/subgroup/project#6"]}`.
A unique number still supports `{"12": [6]}`. Fork requests can appear in review
order; mutation supports same-project feature branches only.

Capture original heads and replay boundaries **before** rewriting any parent.
For a main-based PR, use the original merge base. For a stacked child, use the
original parent head when it is an ancestor; inspect divergent stacks explicitly.
Process each prerequisite through review/publication before preparing its child:

```bash
witful delivery --repo . --remote gitlab:mirror mr rebase --number 5 --old-base ORIGINAL_BASE_SHA \
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
witful delivery mr publish --receipt /tmp/pr-5.json \
    --reviewed-head CANDIDATE_HEAD --checks /tmp/checks.json
```

Preparation selects exactly one remote. The receipt binds its provider, host,
project, remote name and exact fetch/push URL. Publication rejects any binding
drift and uses that receipt, so omit `--remote` for `publish` and recovery `apply`.
Older receipts containing only a repository name must be prepared and reviewed
again; they cannot establish this binding.

Publication runs the supplied checks and all configured pre-commit hooks. Source
or HEAD drift, an unfinished rebase, a moved base, invalid signatures, or a changed
remote head blocks publication. Each rewritten commit is locally verified. The
push uses an explicit expected-head lease, then verifies remote readback and the
head's provider-reported signature. Inspect hosted CI for that revision and update the PR's
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
[PyGithub](https://pygithub.readthedocs.io/en/stable/),
[python-gitlab](https://python-gitlab.readthedocs.io/en/stable/),
[GitHub REST libraries](https://docs.github.com/en/rest/using-the-rest-api/libraries-for-the-rest-api), and
[GitLab client classification](https://docs.gitlab.com/api/rest/third_party_clients/).
Both Python SDKs are community-maintained; neither is an official vendor Python SDK.

## Implementation boundaries

The immutable command registrations in `witful.cli` compose lightweight parsers
from `witful.commands`. The root parses once and invokes the selected domain
handler; standalone domain entrypoints reuse those declarations. Help and lesson
lookup do not import analytics or hosting SDKs.

`delivery.providers.base.Backend` defines inventory, default-branch and signature
operations. `providers.github` and `providers.gitlab` adapt the respective SDKs.
The backend context manager owns client cleanup and redacts API error payloads.
Shared orchestration owns NetworkX ordering, local Git, signing, validation and
receipts. Adding a host requires a backend plus the same inventory and signed-Git
contract tests; it does not add provider branches to CLI dispatch.
