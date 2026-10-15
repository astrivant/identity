# Protected native storage

The native storage implementation keeps typed identity records authoritative in
PostgreSQL or a local bare Git store. It implements the shared binary and encryption
contracts proposed in [RFC 74](https://github.com/astrivant/product-research/pull/74)
and [RFC 75](https://github.com/astrivant/product-research/pull/75).

Implementation is under review. Projection, fork/split, operational evidence and the full acceptance report are being completed
on the implementation branch. Existing managed collections retain their remote
storage block. This document does not authorize a migration or a private pilot.

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
