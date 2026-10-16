# Protected native storage

The native storage implementation keeps typed identity records authoritative in
PostgreSQL or a local bare Git store. It implements the shared binary and encryption
contracts proposed in [RFC 74](https://github.com/astrivant/product-research/pull/74)
and [RFC 75](https://github.com/astrivant/product-research/pull/75).

The [synthetic acceptance evidence](native/acceptance.md) and
[six as-built storage views](native/diagrams/README.md) bind code, schemas and
reference configuration. The [architecture guide](architecture.md) places these
storage boundaries within the wider concept model. Existing managed collections retain
their remote-storage block. Private enrollment and deployment require a separately
reviewed pilot plan.

## Projection implementation

The projection core retains an encrypted outbox intent in the same transaction as
accepted records and their durable receipt. Preparation persists the exact encrypted
history sidecar, Git blob/tree/commit bytes, expected remote parent and a signed
encrypted publication permit before making a remote request. A required-delivery
receipt retains its requirement even when later configuration disables scheduling.
Completion checks use the originally accepted destination set and independently
verified results, rather than assuming an empty queue means successful delivery.

A separately operated gateway owns remote credentials. Its broker grant can unwrap only a separate
permit wrapping-key generation and cannot decrypt exported identity history.
Set `projection.permit_wrapping` to an independently provisioned generation that
is never used for domain data; the gateway broker configuration selects that
generation. The released broker enforces key-generation and action allowlists,
not record-kind restrictions. Permit kind 18 remains authenticated envelope context. Independent public signer pins authenticate that encrypted
history. Current native policy checks both the gateway caller and the original
writer's project/export permissions before publication and result release. No
control-plane database lock is held across key-service or remote Git calls.

The gateway supports one fenced writer per configured destination. It permits only
an exact expected-old update whose new commit retains that parent, or an explicitly
absent initial ref. It fetches into a fresh object database and compares the exact
commit, tree, sidecar and advertised branch before acknowledgment. A lost response
reuses the persisted candidate; competing remote history is reported as divergence.
No automatic merge, ref deletion or unconditional force push is performed. These
semantics follow Git's [explicit lease contract](https://git-scm.com/docs/git-push)
and [fetch behavior](https://git-scm.com/docs/git-fetch).

Retry attempts and backoff are durable. `unknown`, `blocked`, `diverged` and
`remote_verified` remain distinct from the original `durable` receipt. An in-flight
already authorized remote request cannot be recalled by subsequent grant revocation;
revocation prevents new admission and result release. Local inherited process locks
and remote expected-old checks must be paired with the deployment's single-writer
fencing and remote access policy. External writers are outside this profile.

The first projection format contains a bounded full encrypted history snapshot.
Prior retained projection records remain part of that history, so repeated full
snapshots amplify storage. Queue and aggregate archive byte limits refuse work
before exceeding the configured envelope budget; incremental projection is a
separate format change. Returned-object limits do not bound fetched Git packfiles:
the gateway deployment must also bound scratch storage and transfer execution.

Synthetic tests exercise real broker and gateway mTLS, SSH host verification,
remote Git CAS and independent readback, including a lost successful acknowledgment.
A separate required CI stage tests physical backup, synchronous failover and PITR.
The [acceptance report](native/acceptance.md) distinguishes those observations from
production deployment controls and operational service guarantees.

Configure `projection.mode` as `disabled`, `manual`, `interval`, `batch` or
`required`. The complete `projection` object exposes target TLS/grant references,
exporter attribution, interval, batch threshold, entry/byte/lag budgets and bounded
retry controls. Interval delivery becomes due after the oldest intent reaches the
configured interval. Batch delivery becomes due at its count threshold or interval,
so a final partial batch can drain. Required mode attempts accepted work on the
next scheduling cycle and retains the separate completion gate.

```bash
witful native projection status --client CLIENT.json
witful native projection drain --client CLIENT.json --target DESTINATION_UUID
witful native projection check --client CLIENT.json --operation OPERATION_UUID
witful native projection tick --client CLIENT.json --seconds 300
```

`drain` makes one bounded attempt and retains backoff. Add `--scheduled` to honor
disabled/manual/interval/batch deferral; an explicit manual drain can recover
already accepted work after scheduling is disabled. `check` exits nonzero until
all originally required destinations have independently verified receipts. A lost
or accidentally removed pending index entry cannot replace that evidence. `tick`
uses server-owned retry policy for one bounded cycle, handles SIGTERM/SIGINT, and
reports remaining work. A scheduled cycle is distinct from workload completion.

Deploy the [gateway reference](../helm/witful/references/projection/README.md) as a
separate release with `role: projection`. Its configuration retains the original
backend UUID for independent epoch checks but never opens that backend. Use
separate gateway broker-client and transport certificates, an unwrap-only broker
grant limited to the separate permit wrapping generation, pinned SSH host keys and a repository-scoped SSH
identity. Prepare a signed encrypted probe through `native projection probe` and
mount it at `probe.envelope`; readiness verifies current permit-key availability
without needing domain decryption or signing. Reissue the probe after changing
its configured signing/wrapping generations.

Enable `controller.scheduler` on the controller release for one CronJob per
explicit client Secret. Scheduler TLS mounts are separate from the controller's
custody and database mounts. Jobs use a distinct service account, no service-account
token, memory working storage, an explicit deadline and deny-by-default network
policy. Configure approved DNS/controller egress and the controller's corresponding
ingress. The tick interval's Kubernetes schedule limits scheduling precision;
the controller still applies its own interval/batch policy. Server liveness remains
independent of remote availability. Every gateway Git subprocess shares the
remaining complete-operation deadline, including post-push verification.

See [operator provisioning and recovery](native-operations.md) for reviewable SQL
plans, independent grants, deployment checks and recovery procedures.

## Transaction and trust boundaries

The data store receives independently signed AES-GCM envelopes and opaque routing
identifiers. An independently administered PostgreSQL authority selects the active
backend, epoch, policy and acknowledged frontier. Its credential must not be
available to the data database operator. The runtime role cannot modify grants;
a narrowly scoped database function locks the selected grant against concurrent
revocation while PyCasbin evaluates certificate, task, action, record and expiry.

A write validates its complete selected domain view and seals candidates before
acquiring database locks. The authority durably retains the exact ciphertext
candidate before applying it to the data store. The data transaction commits all
objects, the complete ref manifest, receipt and outbox atomically. A control-plane
acknowledgment follows. These are two databases, not a distributed atomic commit:
an interrupted acknowledgment leaves a durable pending candidate and blocks new
operations until exact receipt/frontier readback resolves it.

The independent registry detects restored or divergent data frontiers. Restoring
that registry itself requires a separately trusted recovery procedure; a copy of
its own old state cannot prove its freshness. PostgreSQL failover still requires
operator-enforced fencing of the old primary.

## Data and history

Each domain object, revision, receipt and frontier has a separate encrypted
representation. Meaningful names, ordered parents, semantic hashes, original
source bytes and relationships stay encrypted. The current frontier is a bounded
manifest of pointers, not a writable JSON or JSONL source file.

Native domain validation reuses the existing journal contracts for lessons,
knowledge catalogs and applications, Life snapshots and events, checkpoints,
instances, repertoire and reflection. Selected branch views follow the first
parent. Other ordered parents retain reviewed ancestry without concatenating
competing linear hash chains.

The deterministic CBOR profile admits bounded integers, text, bytes, lists and
string-keyed maps. Domain values use an explicit tagged representation. Finite
binary64 values use their canonical hexadecimal spelling, preserving negative
zero; NaN and infinity are rejected. Original import bytes remain separately
retained rather than being reconstructed from canonical values.

## Acknowledgments and recovery

A stable operation UUID is bound to the complete semantic request inside its
encrypted receipt. An identical retry returns the original target. Changed input
under the same UUID conflicts. Storage also binds exact prepared ciphertext, so
recovery never silently reseals an uncertain write.

`durable` acknowledges the configured native backend. It does not mean a remote
Git push was verified. PostgreSQL can require `remote_apply` with a configured
synchronous-standby policy. Local Git uses fsynced objects and one expected-old
root ref; arbitrary Git readers do not receive a multi-ref snapshot guarantee.

Full-history exports retain exact encrypted transactions, original receipts,
refs, outbox records and source representations. The outer export is signed and
encrypted with current custody or explicitly selected recipient custody. Restore
accepts an empty destination or an exact existing prefix, independently verifies
retained histories and checks the final target. Restoring bytes does not change
which backend the authority selects.

## Exact original Git preservation

`witful.native.original_git.capture` inventories one explicitly selected protected
Git directory and retains canonical object bytes, original OIDs, refs, symbolic
HEAD, available local LFS/submodule assets and repository metadata in signed
encrypted records. Reflogs and available unreachable objects require explicit
retention choices. Import verifies Git connectivity and object IDs, rejects external
links/alternate object stores and rechecks the source before committing.

`original_git.restore` creates a new protected repository, recomputes the original
object IDs, runs Git connectivity verification and reads back retained metadata.
It preserves original commit/tag signature bytes without claiming that archival
retention establishes signer trust. Restored configuration and hooks stay inert
during verification; review them before activating that repository. Existing
paths are never overwritten. The archive explicitly excludes working-tree files,
pruned/provider-hidden objects, external LFS/submodule stores and original pack
layout. The same operations are available through `native original capture`, `list` and
`restore`. Controller settings declare `archives` entries with a name, tenant,
identity, absolute protected path and capture/restore mode. Clients select only
these scoped aliases with `--path`; they cannot provide arbitrary host paths.
Capture uses a stable `--operation` UUID and explicit `--unreachable`/`--reflogs`
flags. List writes its complete inventory through required `--output` into protected
client storage. Restore selects an exact `--record` UUID and configured absent
server path, and writes its inventory through protected `--output`. Retain reviewed
source/restore volumes; the chart can mount existing claims without creating or
removing them.

## Reviewed reconciliation

`witful native ref merge` requires exact target and reviewed candidate heads,
a protected review document and a current `review` grant as well as `write`.
The document contains `reason` and `selections`; each selection names candidate
revision UUIDs in `sources` and an explicitly authored `domain`/`value` record.
An empty selection records reviewed non-adoption. Ordered parents and the
candidate remain intact. The target's existing journal hashes are never rewritten
to make a competing chain fit. The durable prepared operation retains its review
permission, so ordinary write permission cannot finish a revoked review.

## Independently scoped fork and split

`native ref fork` publishes one independently scoped reviewed adoption;
`native ref split` publishes several together. Each target must already have an
empty registered identity, its own current grant and key-service policy, and a
configured `controller.configuration.derivations` alias. Each alias names `name`,
`backend`, `tenant`, `identity`, `grant`, `task`, `epoch` and `policy`. Its backend
must be the current adapter or an explicit configured destination. The caller's
actual TLS subject must be independently approved in every scope. Configuration
creates neither identities nor grants. All participants must share the same
independently administered authority database for atomic publication; cross-authority
splits are rejected.

The parent requires `derive`, `review`, `export` and `write`. Every child requires
`derive`, `import` and `write`. The protected JSON review document contains `reason`
and a `children` array. Each child specifies its configured `destination` alias,
new `ref`, and `selections`; each selection contains source revision UUIDs in
`sources` and explicitly reviewed `domain`/`value` content. These values must form
a valid new child history. No journal hash is silently rewritten to fit a subset.

```sh
witful native ref split --client CLIENT --expected REVIEWED_FRONTIER_UUID \
  --operation STABLE_OPERATION_UUID --input protected-child-review.json \
  --output protected-publication-receipt.json
```

Select the exact source frontier from an acknowledged `native recovery reconcile`
result and review records through `native record history`. A source change before
preparation conflicts. A fork uses the same review shape with exactly one child;
a split requires at least two. Each child receives new honest native adoption
revisions, selected source mappings and the pinned source frontier. Parent and
sibling references grant no traversal. Whole original import files and unselected
ancestry are excluded. The parent's encrypted decision retains all output mappings
and explicit omissions, while its original records remain unchanged.

The controller seals and verifies every candidate before atomically freezing all
participants in the authority database. That durable encrypted preparation includes
the exact parent and child transactions. Data copies happen outside control-plane
locks and remain inaccessible to normal readers and writers. After independent
readback of every exact receipt/frontier, one authority transaction acknowledges
and unfreezes every participant. An injected failure on the final child update
rolls back all acknowledgments, so ordinary clients cannot observe a partly
published split. This is atomic service visibility, not a distributed transaction
across the independent data stores.

An interrupted command must be retried with its unchanged operation ID, review and
configured bindings. It resumes the original bytes and times. Revocation prevents
further progress or result release; it does not undo ciphertext already copied.
Prepared groups cannot be automatically canceled or partially activated. Retain
their fences and restore independently approved access through the administrator's
reviewed recovery process before resuming. No runtime command creates permissions,
removes partially copied data or rewrites the prepared review.

## Migration and reverse migration

The native migration library accepts an explicit inactive destination sharing
the same independently administered authority and identity scope. It verifies a
signed encrypted full-history backup, freezes the source at that exact frontier,
and copies only into an empty or identical-prefix destination. Ordinary access
blocks while the durable migration fence is active. Configuration alone cannot
select a new authority.

The exact sealed cutover batch becomes durable in the control plane before its
first destination effect. That batch retains the encrypted backup, a migration
manifest and a receipt for the next epoch. Independent destination readback
precedes the routing update. An interrupted acknowledgment resumes the same bytes;
a prepared cutover cannot be silently canceled. Explicit cancellation is allowed
before candidate preparation and retains the inactive partial copy.

Reverse migration uses the same protocol. It copies all new destination writes
back to the retained original backend before advancing the epoch again. It does
not restore an old snapshot over acknowledged work. The tests exercise this in
both directions and inject failure after the real destination commit. The controller admits only destinations declared in its signed configuration.
`witful native migration run --client CLIENT --destination BACKEND_UUID --operation UUID`
performs or resumes the transition. `native migration abort` can explicitly
cancel before candidate preparation. After cutover, configure clients and the
selected controller with the receipt's new epoch; the original controller remains
fenced. These synthetic contracts do not constitute a production migration or
private pilot.

## Key lifecycle and recovery commands

`witful native key rotate --client CLIENT --operation UUID --mode MODE` uses
only the controller's configured key generations and independently pinned signer
keys. `rewrap` retains domain ciphertext and nonce while changing the wrapped data
key. `reseal` creates fresh domain ciphertext, nonce and data key. `resign` retains
the wrapped data key and ciphertext and replaces only their signature. Metadata
that points to changed representations is newly sealed in every mode.

The operation requires both `write` and `rotate`, retains an encrypted mapping
between representations, and leaves historical transactions intact. Original
keys remain necessary for historical recovery. Rotation refuses pending
projection intents and does not create, revoke or retire custodial keys.

`native recovery export` writes an already signed encrypted binary package;
`native recovery restore` verifies it into a configured inactive destination and
requires current `export` and `import` permissions. Neither command changes
routing. Read/history compatibility outputs remain restricted to protected
working storage. Recovery packages retain their original key requirements; use
the separate sharing format when a recipient must recover without that custody.

## Recipient-only sharing

`native recovery share` creates a complete, sender-signed encrypted disclosure.
Without `--recipient`, it uses the operating wrapping generation. An explicit
recipient selects a reviewed entry in `controller.configuration.recipients`:
`name`, `tenant`, `identity`, `generation`, base64 DER RSA `public`, and its
independently obtained SHA-256 `fingerprint`. The controller accepts an alias only
for the admitted identity. Recipient private keys never enter its configuration
or API. Changes to this configuration require renewed protection evidence.

```sh
witful native recovery share --client CLIENT --recipient REVIEWED_ALIAS \
  --output shared.cbor
witful native schema --kind recipient > recipient-trust.schema.json
witful native recovery inspect --input shared.cbor --trust trusted-export.json \
  --private-key recipient-encrypted.pem --password-file recipient-password \
  --output reviewed-records.json
```

The export preserves every original encrypted transaction and signature. Its
outer encryption also contains the per-record data keys needed to read that
history, bound to exact contexts, generations and wrapped-key bytes. It never
includes the sender's signing private key or original key-encryption keys. The
recipient can verify and read it without the original broker, including archived
original Git chunks. Complete verification rejects unexplained stored objects,
missing keys, extra keys, altered scopes and invalid histories.

Obtain `trusted-export.json` through an independently reviewed channel. Its closed
schema selects the expected export `context`, exact frontier `generation`, `root`
and hexadecimal `digest`, recipient `wrapping` generation, sender `signing`
generation, and all historical `signers` with public DER keys and fingerprints.
An acknowledged frontier can be obtained with `native recovery reconcile`; select
the intended export context separately and retain both observations with the
handoff. Concurrent source changes cause an exact-frontier mismatch, not silent
acceptance of a different snapshot. Copying pins or expected state from an
untrusted package does not establish provenance or freshness.

Offline inspection requires protected owner-only trust, encrypted RSA PEM and
password files, and a new output on protected working storage. It checks signatures
before decrypting, verifies all retained history, then renders current refs and
revisions once. Exact imported bytes use explicit `source_base64` fields in the
JSON output. The encrypted package remains the complete history archive; the JSON
view does not replace it. The CLI neither activates received instructions nor
imports a disclosure into live authority.

Sharing is an explicit disclosure of all retained history, including old revisions,
archival metadata and recovery keys. Subsequent source revocation cannot revoke a
recipient's existing copy. Review the recipient and retention policy before release;
use a separately reviewed scoped fork/split when only selected content is intended.

## Controller boundaries

One Flask application owns domain, metrics and status blueprints. The production
authentication boundary accepts the verified TLS 1.3 peer certificate supplied by
Gunicorn. Forwarded certificate or identity headers never grant access. Excess
application work is refused immediately; the application has no waiting request queue.

`/live` reports process liveness. `/ready` uses the injected dependency readiness
contract. `/status` and `/metrics` report local worker ownership, rejection/failure
counts, a bounded status and last measured dependency probe durations. They do not
include tenant labels or call dependencies while taking a metrics snapshot.
Operational listeners remain private. `runtime.worker_connections` bounds
Gunicorn-owned connection slots separately from active request threads and the
kernel backlog. These runtime socket queues are distinct from the application's
zero-length waiting queue. Multi-worker counters require aggregation
by the monitoring deployment; one process's counters are not a cluster total.

## Focused validation

The native tests use synthetic keys and independent PostgreSQL roles/databases.
They exercise both local Git and PostgreSQL, including exact retries, stale writes,
tenant/task/certificate denial, restored-frontier rejection, lost acknowledgment,
cross-backend encrypted restore, original bytes and HTTP redaction/admission.

Run with the repository environment and a disposable PostgreSQL administrator URL:

```sh
WITFUL_TEST_DATABASE_URL="$TEST_DATABASE_URL" pytest -n 0 tests/native
```

The database fixtures create and remove uniquely named synthetic databases and
roles. They never migrate a collection. Tests without that variable skip real
database contracts; such a run is not evidence that the backends passed.

## Optional microservice working cache

`witful.native.cache.Reader` wraps the authenticated native client with an optional
in-memory working set. Retention is disabled by default. Enabling it requires a
current protection callback and explicit entry, byte, response and time limits.
Each request contacts the controller, which verifies current authority, decrypts
under current custody and rechecks permission before returning an unchanged token.
The token binds the certificate, scope, grant, task, epoch, policy, frontier and
payload representation. A TTL is never an authorization lease.

The cache stores immutable encoded values and decodes a fresh result for callers.
It has no disk spill, offline fallback or write-acknowledgment authority. Failure
clears retained references. Process shutdown must call `clear`; Python reference
release does not promise secure memory erasure. Expired entries are evicted on the
next read. Rotation or changed frontiers cause fresh payload transfer. This saves
response bytes on a hit, but still performs controller cryptography and a network
round trip; performance claims require measurement. `status` exposes aggregate
local occupancy for the owning microservice's metrics.

## Deployment configuration

The opt-in [native Helm profile](../helm/witful/references/native/README.md) exposes
the complete typed configuration, validated ConfigMap, existing Secret projections,
HA placement, PDB, network policy and runtime probes. PostgreSQL controllers are
stateless; any configured local Git adapter requires a single writer and retained
protected storage. The image includes the standalone broker SDK and Git, without
the broker server or 1Password provider runtime.

`runtime.working_directory` owns runtime temporary files and library caches.
`envelope` configures per-record bytes, item count and nesting; `budget` bounds
aggregate service work. Full-history packages must fit the configured envelope,
service, store and client limits including framing. Crossing any bound fails
explicitly; no incomplete package is reported as a full backup. The controller
requires signed protection evidence and independently verifies local working
storage. A memory-backed Kubernetes volume alone does not establish disabled swap.

### Recovery under execution pressure

`runtime.threads` is ordinary execution capacity and `runtime.admission` cannot
exceed it. `runtime.recovery_admission` reserves separate bounded slots for exact
recovery and migration cancellation. Gunicorn adds those slots and one operational
thread to the execution thread count; `worker_connections` must cover the total.
Verified peer authentication precedes admission. Status and metrics use local
snapshots outside both work quotas. This prevents admitted ordinary work from
consuming every recovery or inspection slot; it is not a denial-of-service guarantee
against arbitrary TLS connections or an unbounded probe flood.
