# CLI

All commands accept `--help`. Commands act on an explicitly selected local
collection and never infer a need to publish it.

```bash
witful init ./my-knowledge
witful lessons --repo ./my-knowledge add --topic Testing --lesson 'Use explicit inputs.' --source 'Team review'
witful lessons --repo ./my-knowledge search explicit
witful --repo ./my-knowledge build
```

Unassigned topics remain visible as Unclassified. Edit `knowledge/catalog.json`
to group exact topic names under disciplines and skills. Generated JSON Schemas
live under `knowledge/schemas/`; `witful --repo PATH check` validates the
sources and schema drift.

| Command | Purpose |
| --- | --- |
| `context --repo PATH snapshot/schema/plan/resolve/check` | Explicit offline working context, individual applicability, and freshness checks; [contract and inputs](context.md) |
| `init PATH` | Create an empty collection; never overwrite an existing directory |
| `lessons [--repo PATH] add/search/check/sync/status` | Source journal and SQLite/PostgreSQL search |
| `[--repo PATH] show [ID]` | Inspect the hierarchy and observed counts |
| `[--repo PATH] record --task ID --discipline ID --concept ID --outcome verified --evidence TEXT` | Append an actual application; repeat `--concept` for co-use |
| `[--repo PATH] build` | Generate schemas, usage charts, hierarchy, and weighted graph |
| `life [--repo PATH] record --input decision.json` | Append a sourced decision with a replay snapshot |
| `life [--repo PATH] show --key KEY --history` | Inspect prior choices and explicit supersession |
| `life [--repo PATH] replay --output-dir PATH` | Reconstruct saved inputs; toolchain drift fails unless explicitly acknowledged |
| `life [--repo PATH] seed` | Transactionally seed an explicitly configured PostgreSQL archive |
| `repertoire [--repo PATH] check/build/record --input use.json` | Validate the toolbox/problem taxonomy, record actual use, and plot task frequency |
| `checkpoints [--repo PATH] record --project PATH --project-id ALIAS` | Record a Git boundary and update its local checkpoint mirror |
| `checkpoints check/diff/build/schemas/sync` | Validate, compare, render, or explicitly mirror checkpoint history |
| `privacy scan [--repo PATH] [--staged] [--terms-file PATH] [--require-complete]` | Inspect filenames and UTF-8 text; [coverage and exit statuses](#pii-scan-coverage) |
| `awareness [--repo PATH] [--config PATH] [--output PATH] build/push/schema` | Render selected figures, explicitly dispatch a resume rebuild, or print wire schemas |
| `sleeve start/checkpoint/backup/finish/status/guard/run/schema` | Isolated sessions, signed backup, termination handling, and verified reconciliation |
| `collection export/verify-export/restore-export` | Signed encrypted current identity copies with an optional recipient public key; [export contract](identity-exports.md) |
| `collection setup/seal/restore/refresh/verify/check-storage/schema` | Private-copy installation, authenticated encryption, and CI figure refresh |
| `reflection [--repo PATH] plan/record/build/check/schema/example` | Periodic decision reassessment, outcome/context plots, and synthetic examples |
| `registry NAME... [--stdin] [--refresh] [--offline]` | Batched PyPI observations, cached for six hours; exit 2 for unknown results |

Life decisions contain `key`, `title`, `task`, `choice`, `rationale`, `source`,
and `concept_ids`; revisions must name the current event as `supersedes`.
The schemas are the authoritative field definitions. Recorded rationale is a
concise engineering explanation, not hidden model reasoning. Application and
decision journals are separate evidence; lookups are not applications.

Registry results are `registered`, `not-registered`, or `unknown`. A 404 is not
proof that PyPI will accept registration. `--ttl-seconds`, `--cache-dir`, and
`--timeout-seconds` control caching and request bounds. A 429 cooldown applies
across the batch and later invocations, even with `--refresh`.

## PII scan coverage

`witful privacy scan` (also `witful-pii scan`) detects declared patterns and private
deny terms in filenames and UTF-8 text. It reports locations and detector names,
never matched values. Filenames that contain a match become digest labels.
`--staged` reads the complete Git index, including its collection configuration;
unstaged replacements cannot hide staged findings.

The JSON-lines output separates three results:

- Findings retain `path`, `line` and `rule`; these are actual detector matches.
- Uninspected content has `status: "skipped"`, a redacted `path` and a `reason`.
  NUL-containing bytes and non-UTF-8 content are unsupported, regardless of extension.
  Configured encrypted envelopes are schema-validated and reported as skipped;
  their plaintext is neither decrypted nor inspected.
- Inspection failures have `status: "error"`, a redacted `path` and a `reason`.
  Unreadable or missing files, oversized files and invalid managed envelopes fail
  inspection. Ordinary text has a 5 MiB limit; envelope limits follow the collection
  transport contract. Symlinks are checked as link text and never followed.

The last JSON object counts `findings`, `skipped` and `errors`. `complete` is true
only when no selected payload was skipped and no inspection failed. An empty
selection is complete. Repository, selection and configuration failures exit 2
with a redacted diagnostic before a summary can be produced.

| Exit | Meaning |
| --- | --- |
| 0 | No matches in inspected content and no inspection errors; unsupported content may be listed as skipped |
| 1 | One or more detected patterns, without inspection errors |
| 2 | Inspection failed, or `--require-complete` was requested and any payload was skipped; this takes precedence over exit 1 |

For a text-only publication gate, run `witful privacy scan --require-complete`.
The default repository hook and CI gate allow binary assets while reporting their
coverage gaps. Neither mode performs OCR, image metadata analysis or archive
extraction. A skipped image is not a detected PII finding or a reviewed image.
Review unsupported content for its intended audience before publication; a passing
pattern scan is not proof of anonymization.

Python callers can use `scan_report()` for typed `findings`, `skipped`, `errors`
and `complete` results. The existing `scan()` interface still returns a tuple of
actual findings, but now raises `ValueError` for file inspection failures instead
of inventing an `unscannable-file` finding. Use the report API when coverage matters.

## Toolbox and problems

`knowledge/repertoire.json` owns `tools` (id, name, kind, purpose, reference)
and `problems` (id, name, optional parent). Parents form an acyclic hierarchy
from broad concepts to concrete problem types. Empty collections are valid.
`knowledge/tool-uses.jsonl` contains explicit observations, never a dependency
scan interpreted as historical use. `repertoire build` emits schemas, an exact
input export, a frequency histogram, and the problem graph under `docs/assets/`.
Problem circles enclose the measured full label and task count, including wrapped
lines. Layer spacing accounts for those radii, keeping nodes disjoint at a fixed
font size; larger taxonomies expand the figure instead of truncating labels.

To record a use, provide a JSON object with `id` and `observed_at` as empty
strings (assigned by the command), a stable `task`, sorted unique `tools`,
`problems`, and `concepts` IDs, and concise actual `evidence`. Referenced IDs
must exist; concepts belong to the main knowledge hierarchy. Repeating the same
observation is a no-op. Later observations of the same task replace its current
counts while retaining previous evidence. Ancestor counts deduplicate each task.
These repertoire plots have their own exported inputs; Life replay covers its
saved lesson/knowledge inputs and does not implicitly archive this separate catalog.

See [project checkpoints](checkpoints.md) for visit ordering, evidence semantics,
database mirroring, and main-branch rendering.

## Awareness publication

`witful awareness --repo COLLECTION build` regenerates selected figures locally.
`witful awareness --repo COLLECTION push` publishes them and requests an authenticated
GitHub rebuild. Both use `knowledge/awareness.json` by default; `--config` and
`--output` override collection-relative paths. `schema` prints the generated
configuration and bundle contracts without reading a collection. See
[setup, authorization, and data boundaries](awareness.md).


## Encrypted private collections

`witful collection setup --repo OWNER/REPO` configures an existing private copy;
`--create` explicitly creates one from a fresh public clone. `--restore` recovers
an existing encrypted collection into an empty local collection directory using saved keys. `--checkout`, `--home`,
and `--key-dir` select the working checkout, local Codex home, and reusable key backup.
`seal` takes `--checkout`, `--source`, and `--key-dir`; it writes encrypted files but
never commits or pushes. `restore` takes `--checkout`, `--key-dir`, and a new
`--output`, with optional `--figures`. `refresh` is reserved for the trusted private
main workflow. `schema` prints the closed configuration and envelope contracts.
See [private collection operations](private-collections.md).

## Multisleeving

Read [the lifecycle, conflict, and recovery contract](multisleeving.md).
`start --repo CHECKOUT --directory NEW_DIRECTORY --name LABEL` begins an isolated
private session from remote main; encrypted copies also require `--key-dir KEYS`.
`checkpoint --repo WORKTREE` signs and pushes the source transport; directly
tracked collections require named `--paths`. `backup` pushes only existing commits.

`finish` merges directly when permitted. Use `--pull-request` when review is
required, and rerun after a merge commit lands. `guard` fails until closure is
recorded and no later work remains. `status` lists local receipts; `schema` emits
the attrs-derived receipt contract. No force pushes or automatic conflict choices.

`run --repo WORKTREE [--paths PATH ...] -- AGENT ARG ...` forwards termination to
the workload, drains writers, checkpoints, and reconciles. `--shutdown-seconds`
defaults to 90 and `--stop-seconds` to 10; require `0 < stop < shutdown`. Workloads
receive `WITFUL_SLEEVE_WORKTREE` and `WITFUL_SLEEVE_SOURCE`. Normal completion
preserves the workload's status, interrupted completion uses `128 + signal`, and
incomplete cleanup returns 2. No hook can save in-memory work after SIGKILL.


## Observed instances

`witful instances --repo COLLECTION start --boundary-id ID --boundary-kind runtime`
creates or reuses an explicit observed boundary. Use `logical-session` when runtime
boundaries are unavailable. Startup returns JSON with the UUID and pending tasks;
coverage defaults to incomplete. `reconcile --instance-id UUID --operation-id KEY
--coverage complete --coverage-source REFERENCE` records a reviewed startup check.
`guard` and `resource` require the active, reconciled UUID.

`task`, `audit`, `observe`, and `stop` require `--instance-id` and a stable
`--operation-id`; retries are idempotent and conflicting reuse fails. `status`
shows current tasks, `check` validates source/reference integrity and reports gaps,
`schemas` emits the sidecar schema, `build` writes bounded native comparison charts,
and `logs` emits private local OTLP/JSON without contacting an exporter.
See [the complete instance API, provenance, and privacy contract](instances.md).

## Life overview

`witful life build` renders `docs/assets/life.svg` and `.png` from the same
decision journal used by `life show`; `life.json` retains raw events and current
choices. README headings such as "Life: choices and revisions" refer to this
"Life: recorded choices" figure, not a separate dataset.

The left panel shows **net change per journal entry**, the discrete first
difference of the former cumulative counts. Each observation contributes +1,
so that series is horizontal. Accepted choices contribute +1 when added or
reinstated, 0 when revised without changing accepted status, and -1 when retired.
Retirement requires an existing choice; source validation rejects an orphan
retirement. Totals remain beneath the panel. Coincident series use different widths and line styles so neither
hides the other. Empty journals show no invented observations.

This is a rate per recorded entry, not per day, and neither growth nor revision
counts measure decision quality. The right panel still counts concept references
in currently accepted choices. Historical replay retains original snapshots;
the renderer change follows the existing explicit drift-acknowledgement contract.

## Completion audits

`witful completion --repo COLLECTION plan --task TASK --workspace PROJECT --output
COLLECTION/.witful/completion/review.json` enumerates the entire hierarchy for an
explicit review. `check --task TASK --workspace PROJECT --input PATH` rejects gaps
and stale state. `schema` emits its closed source contract. `hook-config --identity
NAME` prepares a synchronous Codex hook definition for native user review and trust.
See [coverage, handoff, storage, and hook behavior](completion.md).

## Repository delivery

`witful delivery` provides read-only `pr show`, isolated `pr rebase`, reviewed
`pr publish`, and resumable `recovery plan` / `recovery apply`. Read the
[delivery contract](delivery.md) for required inputs, exact-head leases, signed
small-first batches, review boundaries, and interrupted-run recovery.

## Collection storage verification

`collection check-storage --path PATH` verifies host encryption evidence. Repeat
`--path` for keys, indexes, and temporary storage. `collection verify --checkout PATH
--signing-fingerprint TRUSTED_SHA256 [--figures]` authenticates ciphertext against
an independently retained signing identity. See [data protection](data-protection.md).

## Continual learning

`witful reflection --repo COLLECTION plan --history-repo CHECKOUT` prepares a
private review brief using full Git history. `record --input assessments.json`
accepts its complete reviewed batch; `build --output-dir PATH` renders current
assessments, and `check` validates the journal. `schema` prints generated contracts.
`example --output-dir PATH` renders synthetic public demonstration data only.
See [cadence, rubric, and evidence requirements](continual-learning.md).

## Collection key rotation

`witful collection inventory` lists current managed ciphertext. `seal-file` and
`restore-file` explicitly register and recover opaque files outside the source
archive allowlist. `rotation-keys` writes a private candidate; `rotate` prepares
verified previous/current snapshots without editing the active checkout.
`prepare-refresh` and `publish-refresh` are trusted CI stages. `promote-keys`
explicitly projects adopted keys to existing primary Actions secrets.
See [inputs, limits, recovery and publication](key-rotation.md).

## Command composition

The root command builds one argparse hierarchy from `witful.commands` and parses
once. [`Command`](../pkg/witful/commands/builder.py) is an immutable recursive node:
a group owns `children`, and an executable leaf names a lazy runtime `module`
implementing `execute(args, parser)`. Each node can declare local arguments and
aliases. The same `register`/`populate` contract works at every tier, including
standalone entrypoints; only the selected leaf's runtime is imported.

The [delivery tree](../pkg/witful/commands/delivery.py) demonstrates
`delivery -> pr/mr -> show/rebase/publish` and `delivery -> recovery -> plan/apply`.
Register a tree beneath another group with `register(subparsers)`, or populate a
fresh standalone parser with `populate(parser)`. Parse once at the entrypoint and
call `dispatch(namespace)`. Existing domain builders with their own subparsers can
remain executable leaves during incremental adoption.

Groups require a child, while leaf handlers receive their own parser so domain
errors identify the complete command path. Set `destination` only when the runtime
needs a child selection field, and use distinct fields at different levels.
Declare shared options once at the owning ancestor, before its child token; avoid
redeclaring defaults on descendants where they can overwrite explicit values.
Keep declarations free of runtime imports, network calls and storage writes.

Follow [argparse's subcommand contract](https://docs.python.org/3/library/argparse.html#sub-commands).
Extend the [builder regressions](../pkg/witful/commands/tests/test_builder.py) for
new nesting behavior, including aliases, reusable mounts, parent options, required
children and runtime-free help. Keep dispatch out of manual `sys.argv` slicing.

`witful delivery --remote github:origin --remote gitlab:mirror pr show` combines
provider inventories. `mr` is an alias for `pr`; rebase preparation selects one
remote and publication uses its bound receipt. See [delivery inputs](delivery.md#inputs-and-prerequisites)
for SDK authentication, provider evidence and operation boundaries.

## Repository codegraphs

`witful codegraph setup` explicitly prepares optional 1Password broker custody.
Provisioning defaults to on for this command; `--no-provision` and explicit vault
field references reuse existing credentials. See [setup and recovery](codegraph-setup.md).

`witful codegraph build` and `witful codegraph query` operate on explicitly enrolled
engineer-only encrypted extensions. See [inputs, commands and custody](codegraphs.md).
The SDK worker is optional and uses a separate locked runtime; the CLI never
automatically installs it, enrolls repositories or provisions keys.
