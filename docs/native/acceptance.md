# Protected native storage acceptance

This package implements the protected-state contracts in
[RFC 74](https://github.com/astrivant/product-research/pull/74), including the native
storage dependencies in [RFC 75](https://github.com/astrivant/product-research/pull/75).
It contains synthetic implementation and recovery evidence, operational provisioning
commands, and [six versioned as-built views](diagrams/README.md). Private enrollment,
production deployment, host attestation and the RFC's later bounded private pilot
remain separate operator decisions.

## Implemented contracts and review evidence

| Contract | Implementation and verification |
| --- | --- |
| Typed canonical binary records and cross-language digest domain | [Python codec tests](../../tests/native/test_codec.py), [shared vectors](../../tests/native/resources/codec-v1.json), [JavaScript codec checks](../../scripts/documentation/native-codec.test.mjs): 15 valid and 9 invalid vectors, including byte strings, signed integer bounds and Unicode |
| Signed ciphertext before unwrap; fresh payload encryption; independent custody | [Envelope tests](../../tests/native/test_envelope.py), [released broker SDK/server mTLS](../../tests/native/test_broker_transport.py). Runtime consumes only the separately published SDK; gateway grants admit only the permit wrapping generation and unwrap action |
| Separate data/authority roles, forced RLS, scoped policy and fencing | [Service](../../tests/native/test_service.py), [operator plan and privilege tests](../../tests/native/test_administration.py), [configuration/evidence checks](../../tests/native/test_config.py) |
| Exact operation recovery and no guessed absence | [Settled recovery](../../tests/native/test_settlement.py): real PostgreSQL and Git operations, retained preparation, lost replies and blocked conflicting work |
| Search, branch/tag, reviewed ancestry and independently scoped fork/split | [Reconciliation](../../tests/native/test_reconciliation.py), [derivation](../../tests/native/test_derivation.py), [recursive API/CLI](../../tests/native/test_derivation_cli.py); last-child acknowledgment failure rolls back the whole authority publication |
| Signed encrypted backup, both migration directions, reverse catch-up after new writes | [Backup](../../tests/native/test_backup.py), [migration](../../tests/native/test_migration.py), [rotation](../../tests/native/test_rotation.py) |
| Original Git object/signature bytes and explicit history inventory | [Original Git archive](../../tests/native/test_original_git.py); preserves exact OIDs under the original format. New projection commits honestly represent new encrypted exports |
| Recipient-only encrypted sharing and retained historical custody | [Sharing](../../tests/native/test_sharing.py), [offline CLI](../../tests/native/test_sharing_cli.py); recipient restoration succeeds without original sender keys |
| Optional memory L1 and current authorization on every hit | [Cache tests](../../tests/native/test_cache.py); disabled by default, no durable plaintext cache, outage/revocation blocks reuse |
| Durable projection intent, exact prepared bytes, scheduling and required-target completion | [Intents](../../tests/native/test_projection_intents.py), [preparation](../../tests/native/test_projection_preparation.py), [worker/recovery](../../tests/native/test_projection_worker.py), [CLI](../../tests/native/test_projection_cli.py) |
| Isolated gateway, remote CAS and independent verification | [Gateway policy](../../tests/native/test_projection_gateway.py), [lost-ack Git transport](../../tests/native/test_projection_transport.py), [real gateway mTLS, released broker and SSH](../../tests/native/gateway_transport.py) |
| One Flask app, private operational endpoints and owned shutdown | [API](../../tests/native/test_api.py), [real Gunicorn transport](../../tests/native/test_native_transport.py), partial-startup cleanup regression in [configuration tests](../../tests/native/test_config.py) |
| CloudNativePG CRs, stateless controller HA and isolated gateway/scheduler controls | [Chart references](../../helm/witful/references/README.md), chart tests and the CI orchestration job. No handwritten PostgreSQL StatefulSet |
| Recovery and status under saturated ordinary execution | [Event-barrier API tests](../../tests/native/test_api.py), [reserved runtime capacity](../../pkg/witful/native/gunicorn.py), [configuration refusals](../../tests/native/test_config.py) |
| Current committed provider API contracts on every PR | [Freshness gate](../../.github/workflows/stage-provider-contracts.yml), [real SDK request construction and schema tests](../../scripts/ci/tests/test_provider_contracts.py) |
| Physical backup, WAL decoding, synchronous primary-loss recovery and PITR | [Required physical stage](../../.github/workflows/stage-native-storage.yml), [actual drill](../../tests/native/test_physical.py), [retained receipt](evidence/physical.json) |

The [source checkpoint](https://github.com/astrivant/identity/commit/3300191abca6ebe888219f352e4dcb137519fbe3)
passed [hosted CI](https://github.com/astrivant/identity/actions/runs/38811762050),
including Python tests, source/type/schema checks, provider contracts, images/chart,
privacy, distributions, and the required physical storage stage. Its local native/chart
suite passed 184 tests with five deliberate skips (two backend-specific cases, two
opt-in benchmark profiles, one separately executed physical drill). Subsequent transport,
diagram and cleanup changes are identified by the PR's current revision and checks;
the checkpoint result is not a claim about an untested later commit.

## Physical recovery evidence

The retained [CI receipt](evidence/physical.json) binds actual code, SQL, dependency
and test inputs by SHA-256. Its source is the CI merge revision of the linked source
checkpoint. The drill creates disposable PostgreSQL primary, synchronous standby and
inactive restore instances on separate persistent volumes. It verifies a real
`pg_basebackup`, archives WAL, kills the primary, promotes the standby, rejects an old
epoch, and restores a separate instance to an explicit earlier recovery point.

All three acknowledged generations survive the tested synchronous failover. PITR
recovers the intentionally selected second generation and explicitly excludes the
later third generation. These are observed frontiers, not zero-loss promises for an
unexamined deployment. Exact local times and decoded full-page counts remain in the
receipt. PostgreSQL's [continuous archiving contract](https://www.postgresql.org/docs/current/continuous-archiving.html)
requires backup and WAL continuity; replication alone is not a backup.

The leakage test examines decoded WAL full-page images, a decoded custom-format dump,
and database diagnostics. A 500,000-character TOAST positive control proves that
compressed content was decoded and inspected. The native payload canary is absent.
Opaque identifiers, size, timing and structural metadata still exist. The synthetic
fixture intentionally substitutes storage attestation and uses a local test database
connection; it does not attest encrypted production disks, nonswappable host memory,
Kubernetes/operator promotion or a real network partition.

## Bounded performance experiment

Measurements use [source 3300191](https://github.com/astrivant/identity/commit/3300191abca6ebe888219f352e4dcb137519fbe3),
Python 3.13.16 on macOS arm64, a persistent Docker PostgreSQL volume, and local Git
filesystem storage. Both paths include real envelope cryptography, an independent
PostgreSQL authority and local fsync/WAL acceptance. Neither promises remote Git or
synchronous-replica acknowledgment in this experiment. Docker VM and host filesystem
paths differ, so this is a local development comparison, not a matched hardware trial.

The [runner](../../scripts/native/benchmark.py) completes the Git baseline first,
then records a baseline SHA-256 and a maximum PostgreSQL/Git append-p95 ratio of 0.70
before running the candidate. The [preregistration](evidence/benchmark/benchmark-preregistration.json)
and raw [Git](evidence/benchmark/benchmark-git.json),
[PostgreSQL](evidence/benchmark/benchmark-postgres.json) and
[experiment](evidence/benchmark/experiment.json) records are retained.

| Initial branch depth | Git append p95 | PostgreSQL append p95 | Candidate / baseline |
| --- | ---: | ---: | ---: |
| 16 | 1615.44 ms | 554.14 ms | 0.343 |
| 64 | 4393.91 ms | 1596.92 ms | 0.363 |

Both profiles meet the preregistered local target. Each has one writer, three warmup
reads and eight trials; profiles share a growing identity frontier. Raw exact-read,
head, history, append and branch latencies, cold reads, CPU time and process maximum
RSS are retained. With eight samples, p95 and reported p99 are the sample maximum;
seeded bootstrap intervals do not establish population tail latency. Process RSS is
in platform units and excludes the PostgreSQL server and Docker VM.

This bounded run excludes hosted Git, key-service network latency, synchronous-replica
performance, L1 hit timing, large histories, multiple writers, fork/split/merge timing,
production cost and capacity planning. It does not select a production backend. Full
history validation and snapshot retention are visible costs; PostgreSQL reduces local
Git process/object overhead here, while cryptography, history size, authority round
trips and remote replication can dominate another deployment. Measure its complete
required durability path before sizing CPU, memory, connections or network capacity.

The preliminary trial failed its harness selection: `-k git` matched the shared test
function name and selected the PostgreSQL candidate before the baseline existed. The
candidate correctly refused that missing preregistration. The ensuing Git trial was
interrupted during a custody-boundary correction; it produced no accepted result.
The retained run uses exact node IDs and persistent PostgreSQL storage. Failed and
interrupted observations are excluded from the table, not silently counted as passes.

Reproduce using the locked development environment, Docker, Git and a fresh output
path:

```bash
python -m scripts.native.benchmark --output .cache/native-benchmark-RUN
```

This owns only uniquely named synthetic databases, Docker resources and test files.
Each backend trial has a ten-minute bound. A failed baseline prevents candidate
execution; interruption leaves result/log evidence and attempts owned-resource cleanup.

## Reproduce acceptance

Install the committed lockfile with the `postgres native` extras and development
dependencies. Start a disposable supported PostgreSQL instance and provide its
administrator URL only through the environment. The tests create and remove unique
databases and least-privilege roles. Git, OpenSSH client and `/usr/sbin/sshd` must be
available for the real transport tests; their synthetic listener is loopback-only and
uses temporary keys, without changing system SSH configuration.

```bash
WITFUL_TEST_DATABASE_URL="$TEST_DATABASE_URL" pytest -n 0 tests/native -q
WITFUL_NATIVE_PHYSICAL_TESTS=1 WITFUL_NATIVE_EVIDENCE=.cache/native-physical pytest -n 0 tests/native/test_physical.py -q
npm --prefix scripts/documentation test
python -m scripts.native.diagrams --check
pre-commit run --all-files
```

Ordinary tests skip the opt-in physical drill and benchmark. CI runs the physical drill
in its own required parallel stage. Without the database URL, native backend tests
skip rather than manufacture evidence. Raw hosted recovery logs and JUnit results are
retained as synthetic CI artifacts; this document links the compact reviewed receipt.

## Delivery CLI integration

The current `witful delivery pr show --json` command was exercised against both
public checkouts using the maintained provider SDKs and existing authentication.
Its open-PR numbers and head revisions matched an independent host inventory:
[Identity #24](https://github.com/astrivant/identity/pull/24) and
[broker #15](https://github.com/astrivant/1password-agent-broker/pull/15).
The coordinated broker implementation and packaging fix are already merged, so an
open-only inventory correctly omits them. [Broker #17](https://github.com/astrivant/1password-agent-broker/pull/17)
was merged during this review; its typing-marker fix awaits a later package release.
The consumer still uses the independently verified published SDK release. No merge,
rebase or publication is performed by this inventory command.

## Operational limits and next deployment gate

The [operator guide](../native-operations.md) covers independent role/key provisioning,
exact configuration attestations, admission, recovery, backups and reverse migration.
Current source-history and projection snapshots are bounded full representations;
retained projection history amplifies storage. The implementation refuses configured
limits instead of silently trimming history. Incremental projection needs a versioned
format and separate review. Gateway packfile growth also needs a deployment storage
quota, in addition to application byte/time limits.

The optional live Git-object server and legacy Git-only flattening are outside this
implementation. Exact original-Git archives and the canonical native-history sidecar
are supported. The managed collection's existing remote database block stays active.
A private pilot must independently attest actual disks/WAL/backups/swap/diagnostics,
select RPO/RTO and fencing ownership, verify the real chart/operator deployment,
rebind the diagrams to that configuration, test recovery and reverse cutover, and
obtain authorization for the named identity and destination. No real private records,
keys or production services were migrated during this implementation.
