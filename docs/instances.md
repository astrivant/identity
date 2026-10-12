# Observed instances and native evidence

An instance is one **explicitly observed runtime boundary**, identified by a UUID
allocated at first observation. A logical conversation, wake, retry, compaction,
project checkpoint, and model configuration are different concepts. When the host
does not expose a reliable runtime boundary, record `logical-session` and say so.
Do not guess a runtime restart, backfill historical UUIDs, or infer served models
from requested configuration. UUIDs are correlation identifiers, not secrets.

This feature is opt-in local instrumentation. It cannot automatically identify a
platform runtime or prove that every external task source was checked. Host
integrations must supply honest boundary evidence and perform the reconciliation.
Existing uninstrumented actions remain uncorrelated rather than receiving invented
historical metadata.

## Startup and action gate

```bash
witful instances --repo COLLECTION start \
  --boundary-id host-runtime-opaque-id --boundary-kind runtime \
  --session-id logical-session-opaque-id \
  --requested-model configured-model \
  --template-revision FULL_TEMPLATE_GIT_SHA
```

Use the host's actual stable runtime identifier, if exposed. Otherwise explicitly
choose and persist a stable logical-session key with `--boundary-kind logical-session`.
Repeating `start` for the same identity, boundary kind, and boundary key returns
the same UUID, even after wakes, retries, compaction, or task interruption. New
observed boundaries create new UUIDs. Preserve the returned `instance_id` in the
host's durable task context. Do not derive it from each message or clock tick.

Startup returns JSON containing `instance_id`, the original start `event`, and
its exact `pending_tasks` frontier. `status` reports the latest task projection.
Review the outstanding tasks, original requests, current outcomes, and relevant
external task sources before declaring complete coverage. When a source is
unavailable, coverage stays incomplete; recording an incomplete reconciliation
still preserves what is known.

```bash
witful instances --repo COLLECTION reconcile \
  --instance-id UUID --operation-id startup-review-1 \
  --coverage complete --coverage-source reviewed-task-sources-reference
witful instances --repo COLLECTION guard --instance-id UUID
```

Coverage defaults to `incomplete`. `complete` requires an explicit evidence source;
it is a caller assertion, not a claim that Witful inspected an inbox or task service.
`guard`, `resource`, `instance_resource`, new audit actions, and transitions to
`running` fail unless the active instance has complete coverage. A subsequent task
change by another instance invalidates the gate and requires a fresh reconciliation.
Read-only inspection and recording pending/blocked handoffs remain available.
An uncertain action outcome should remain `unknown` and its broader task open.

A retry key is scoped to one UUID. An identical retry returns the original event,
including its original evidence and timestamp. Reusing the key with different
payloads fails. Repeated `start` does not silently upgrade coverage or rewrite
metadata; use a new explicit reconciliation operation. After `stop`, the same old
boundary still resolves to its original UUID but cannot act again. A genuinely
new runtime needs a new observed boundary, not a rewrite of the stopped record.

## Provenance and links

`--served-model MODEL --model-evidence REFERENCE` requires an authoritative host or
provider observation. Omit both when unavailable; `--requested-model` is stored
separately. Initial provenance is immutable. It is not a promise that routing or
a provider's model will remain constant for every later request. Per-request model
observations belong in that request's own audit instrumentation.

The definition records its full Git HEAD, separately observed dirty state, package
version, and an optional explicit full `--template-revision`. Non-Git sources keep
revision and dirty state unknown. A dirty checkout does not claim its current
contents equal HEAD. Git paths, remotes, authors, messages, and diffs are not stored.
Git metadata and source snapshots are observations, not an atomic Git transaction.

Use `--parent-instance-id UUID` for an observed child and
`--predecessor-instance-id UUID` for a verified replacement or restoration. Both
must reference already recorded local UUIDs; unknown relationships remain absent.
A logical-session UUID is exposed as `witful.instance.id`, never as an observed
runtime `service.instance.id`. `witful.session.id` remains a separate optional
logical-session reference. Runtime UUIDs expose both instance attributes.

## Durable task handoffs and actions

```bash
witful instances --repo COLLECTION task \
  --instance-id UUID --operation-id task-create-1 --task-id task-opaque-id \
  --status pending --summary 'Review the verified result' --source request-reference
witful instances --repo COLLECTION task \
  --instance-id UUID --operation-id task-run-1 --task-id task-opaque-id \
  --status running --summary 'Review the verified result' --source request-reference \
  --previous PRECEDING_TASK_EVENT_ID
witful instances --repo COLLECTION audit \
  --instance-id UUID --operation-id action-1 --action tool.inspect \
  --outcome succeeded --request-id existing-request-id
witful instances --repo COLLECTION observe --instance-id UUID --operation-id observation-1
witful instances --repo COLLECTION stop --instance-id UUID --operation-id stop-1
```

Task states are `pending`, `running`, `blocked`, `succeeded`, `failed`, and
`cancelled`. The last three close that specific task attempt; a failed attempt does
not resolve the user's broader request. Keep or create the appropriate follow-on
task when work remains. Updates require the exact preceding task event ID, so a
stale concurrent writer cannot silently take ownership. Completed task history is
immutable; new work uses a new task ID. Stop does not discard unfinished tasks.

Boundary, session, operation, task, action, outcome, and request IDs use 1–256 characters
from letters, digits, `.`, `_`, `:`, `/`, and `-`, starting with a letter or digit.
Other metadata is bounded to 512 printable characters. These syntactic limits
are not secret detection: use opaque identifiers and concise sanitized references.
Never put credentials, raw tool arguments, source text, hidden reasoning, or
personal messages in correlation fields. Task summaries stay in the private
source/export; log output does not include them.

Audit records can include existing `--trace-id` (32 lowercase hex characters) and
`--span-id` (16), both nonzero. A span requires its trace. Do not invent provider
request IDs or pass extra correlation arguments to a connector that does not
support them. Use the local audit layer when the connector has no metadata field.

## Native snapshots and plots

The source is a separate append-only `knowledge/instances.jsonl`. Start and observe
reuse native content-addressed Life `Snapshot` objects in `knowledge/snapshots/`,
and reference existing Life and checkpoint heads. They never rewrite lessons,
applications, native decision/checkpoint journals, historical snapshots, or schemas.
The existing native knowledge hierarchy and checkpoint `SkillState`/fact comparison
logic remain authoritative. No parallel understanding graph or invented score is
introduced.

```bash
witful instances --repo COLLECTION check
witful instances --repo COLLECTION schemas
witful instances --repo COLLECTION build --limit 8
witful instances --repo COLLECTION status
```

Build writes `docs/assets/instance-comparisons.svg`, `.png`, and the full private
`instances.json` export. `--output-dir` changes that destination. The chart shows:

- Native skill additions/removals and name or parent changes
- Active native insight additions/removals/content revisions
- Native lesson and observed-use memberships per skill
- Active Life decision additions, explicit retirements, and revisions

Membership counts can overlap across skills; an insight edit also revises its
parent lesson digest. Counts describe recorded evidence, not understanding,
competence, intelligence, or a model's causal contribution. Baseline evidence is
never counted as newly acquired. Missing evidence is a gap, not zero change;
corrupt retained evidence fails validation. An empty collection renders an honest
empty-state panel with no fabricated graph.

Rows follow observed start order within the same native identity and compare each
instance's latest retained endpoint with the preceding instance endpoint. Visible
labels include UUID, boundary kind, the latest retained evidence endpoint UTC time,
and startup model/definition SHA/dirty metadata. The startup commit does not identify
later working-tree evidence; no end-commit equivalence is claimed. Overlapping observation windows are marked;
endpoint times can run backward in start order. These comparisons are not causal
attribution and must not be described as time-exclusive work by one instance.
The full export retains every event and comparison despite the 1–20-row display limit.

## Private logs and host API

`witful instances --repo COLLECTION logs` prints a local OTLP/JSON
`ExportLogsServiceRequest`. It sends no network traffic, installs no exporter, and
reads no OTLP endpoint configuration. Resource attributes identify the recorded
instance; log attributes identify event, operation, action, outcome, and optional
existing request. Timestamps are integer nanoseconds encoded as decimal strings.
Trace/span IDs use OTLP's hexadecimal JSON convention. Tests normalize those two
fields to generic protobuf JSON bytes and round-trip against the official
OpenTelemetry protobuf message with unknown-field rejection.

The envelope follows [OTLP JSON encoding](https://opentelemetry.io/docs/specs/otlp/#json-protobuf-encoding).
`gen_ai.request.model` and `gen_ai.response.model` use the
[model attribute vocabulary](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/)
for the initial recorded model metadata. They are resource-level instance
annotations here, not evidence of a particular provider request or full GenAI
span semantic-convention conformance. Unknown response metadata remains `unknown`.
Other fields are under `witful.*`. Logs are private and may expose source aliases
and relationships even without source text.

Python integrations import `start`, `record`, `read`, `pending_tasks`,
`require_ready`, and `instance_resource` from `witful.instances.journal`.
`instance_resource(root: Path, instance_id: str) -> dict[str, str]` validates an
existing active, fully reconciled UUID and returns bounded attributes. It does
not create an instance as a side effect. Use these attributes only in supported
local logging fields. `record` takes immutable `Task` or `Audit` models from
`witful.instances.models`. `start` returns an immutable start `Event`; no host
instrumentation is silently installed.

## Persistence, concurrency, and privacy

Writers lock `.instances.lock`, validate the complete chain, preserve the exact
existing byte prefix, atomically replace the extended file, and fsync the file and
containing directory. A retry after publication returns the original event. Native
snapshots are written first; interruption before event publication may leave an
unreferenced immutable snapshot but cannot publish a dangling new record.
Truncated, conflicting, or corrupt journals fail closed and are preserved for
review. The content chain detects corruption; it is not an authenticated signature
against someone able to rewrite the entire source. POSIX advisory locks and durable
local storage are required; this is not a distributed multiwriter database.

For encrypted collections, the source allowlist includes the instance journal and
native snapshots. Seal/restore and sleeve checkpoint fingerprints retain both.
Concurrent sleeve branches still require reviewed reconciliation; this feature
never auto-merges divergent hash chains or chooses one side. Keep local databases,
credentials, locks, and exported logs outside published source bundles. Figure
publication remains separately opt-in; `instance-comparisons` is an available
awareness figure, disabled unless selected. Readable figure settings can expose
model, revision, UUID, and timing labels in Git history. Review before publishing.
