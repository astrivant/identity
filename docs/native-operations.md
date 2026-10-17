# Native storage operations

The controller does not administer databases, grant access, generate deployment
attestations or create broker keys. An independent operator provisions those
boundaries, reviews the generated plans and supplies scoped runtime credentials.
Use the [storage contract](native-storage.md) and the
[native chart reference](../helm/witful/references/native/README.md) together.
Review the [as-built views](native/diagrams/README.md) and
[synthetic acceptance report](native/acceptance.md) before selecting a deployment.
All examples below use explicit placeholders, not a working production enrollment.

## Provision the two databases

Create separate dedicated data and authority databases and separate existing
unprivileged login roles using the database operator. Runtime roles must not own
the databases or tables, inherit other roles, bypass RLS, replicate or administer
roles. Keep administrator connections outside controller and scheduler Secrets.
Use verified TLS connections and independently managed credential delivery.

Generate SQL in protected operator working storage, then review it:

```bash
witful native administration schema --kind data --role native_data_runtime --output DATA.sql
witful native administration schema --kind authority --role native_authority_runtime --output AUTHORITY.sql
psql "$DATA_ADMIN_DATABASE_URL" --no-psqlrc --set=ON_ERROR_STOP=1 --file=DATA.sql
psql "$AUTHORITY_ADMIN_DATABASE_URL" --no-psqlrc --set=ON_ERROR_STOP=1 --file=AUTHORITY.sql
```

The plans are transactional and reject privileged runtime-role preconditions before
schema changes. They install packaged schemas and grant only native runtime
permissions. Data records, receipts and outbox objects are insert-only to the data
role; only heads are mutable. The authority runtime can advance registry fences
but cannot insert identities or create, modify or revoke grants. Dedicated database
ownership matters: these plans revoke public schema creation. Existing deployments
must review their grants and dependencies before applying a plan.

Each generated plan includes its own `BEGIN` and `COMMIT`. Use the `psql`
invocation above without `--single-transaction`. A Python operator applying an
already reviewed plan must use a fresh `psycopg.connect(..., autocommit=True)`
connection. Autocommit here delegates transaction ownership to the plan; it does
not make its statements independent commits. On failure, close that connection
or call `rollback()` before reusing it. Keep ordinary runtime transactions unchanged.
See [Psycopg transaction management](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).

Generate the closed enrollment input contract with:

```bash
witful native administration contract
witful native administration enroll --input ENROLLMENT.json --output ENROLLMENT.sql
psql "$AUTHORITY_ADMIN_DATABASE_URL" --no-psqlrc --set=ON_ERROR_STOP=1 --file=ENROLLMENT.sql
```

An enrollment specifies `access` (scope, actual client-certificate SHA-256,
explicit grant/task/policy UUIDs and initial epoch 1), backend UUID, exact actions,
record UUIDs or an explicit whole-identity wildcard, start and expiry. The plan
only inserts a new empty scope and one grant. Repeating it fails on existing
identity state; it never resets an epoch, overwrites history or broadens an existing
grant. Additional grants, revocation and policy changes are reviewed authority
operator transactions. Revocation must commit before it is considered effective;
currently admitted work may finish before that commit acquires its grant lock.

### Interpret contract-test database logs

The disposable native contract tests deliberately exercise rejected operations.
`witful_native_registry_pkey` duplicate-key errors are expected when
`test_enrollment_is_insert_only_and_runtime_cannot_administer` submits the same
plan twice, and when competing-enrollment tests race two plans for one scope.
These tests assert the rejection and verify the retained state. Permission-denied
and injected rollback errors also exercise failure boundaries. Test administrator
connections identify themselves through `application_name`; the duplicate probe
uses `witful-native-test:reject-duplicate-enrollment`. Include `%a` in PostgreSQL's
`log_line_prefix` when the operator needs that label in text logs.

`there is already a transaction in progress` is not an expected test outcome. It
means a plan's `BEGIN` was submitted inside an existing transaction. The native
fixture checks server notices to catch that mistake locally and in CI. A duplicate
registration outside an intentional negative test remains a real enrollment conflict:
inspect the existing scope and grant, roll back the failed attempt, and have the
authority operator review the intended action. Do not replace enrollment with an
upsert or bypass the unique constraint to make the error disappear.

Provision the separate broker policy with matching trusted client, tenant,
identity, task, authority and policy bindings. A native grant does not grant broker
custody. A projection gateway receives unwrap authority for the separate permit wrapping generation only, with
separate credentials and no data-database login. Never copy controller signing or
domain-unwrapping credentials into the gateway or scheduling jobs. Retain old permit
wrapping generations while accepted work references them. Disabling scheduling or
changing the configured generation cannot retarget an already accepted intent.

## Select durability and deploy

Review the complete server schema and chart ConfigMap, protection evidence and
independent signer fingerprints. Protection evidence must come from actual
storage, swap, diagnostics, backup and retention inspection. The controller only
verifies the signed, scoped, expiring evidence; it cannot prove the host's storage
security by itself. Production database connections require `sslmode=verify-full`.

For native PostgreSQL, choose local WAL durability or `remote_apply` explicitly.
The latter requires a configured synchronous standby and refuses operation when
that condition is unavailable. The authority database also needs the agreed
availability, durable-storage, backup and fencing policy. A replicated data
cluster alone does not make the complete control/key service HA.

Use the CloudNativePG dependency or an existing compatible operator, then apply
Witful's Cluster CR and reviewed ConfigMaps/Secrets. Run the configured readiness
probe, an explicitly provisioned synthetic canary append/read and a recovery export
before enrolling private traffic. Keep deployment and upgrade logs free of source
records and credential values. Chart uninstall must retain database storage and
backups according to the operator's explicit policy; it does not authorize deletion
or migration. The local Git profile requires a single writer and durable protected
storage; the gateway requires one fenced writer per destination.

## Resolve an unknown operation

Retain the original operation UUID and exact inputs. Do not retry with a fresh UUID
because a timeout might follow a successful durable write. Inspect current authority
and restore unavailable dependencies, then use:

```bash
witful native recovery reconcile --client CLIENT.json
witful native projection status --client CLIENT.json
witful native projection drain --client CLIENT.json --target DESTINATION_UUID
witful native projection check --client CLIENT.json --operation OPERATION_UUID
```

The first command reconciles the exact retained normal-write preparation. Grouped
fork/split recovery uses the original `ref fork` or `ref split` command with the
same review and child aliases. Every group member remains fenced until all exact
candidate bytes verify and one authority transaction publishes every child. Do not
manually clear `pending` or `transition`, advance a generation, recreate a receipt
or reinterpret a missing response as failure.

Projection status gives the authorized durable queue size, byte count, oldest age,
retry state and verified frontier. `/metrics` and `/status` report worker-local
admission and dependency timing; their zero admission queue does not assert that
the durable projection backlog is empty. Use the authenticated projection status
for that identity's queue and completion gate. Remote divergence requires reviewed
reconciliation and a new explicit destination contract, never an automatic force
push. Disabling scheduling preserves accepted delivery obligations.

## Recover history and routing

Export an encrypted complete-history recovery package before planned migration or
key changes. Retain its independently trusted signer fingerprint, expected scope,
frontier, schema/profile, inventory and all referenced historical wrapping keys.
Test restoration into a separately provisioned inactive backend. Current files
rotated to new keys do not rotate retained Git history, old exports or backups.
Recipient sharing is a separate full-history disclosure with a reviewed recipient
key; a successful sender export does not prove the recipient has restored it.

```bash
witful native recovery export --client CLIENT.json --output BACKUP.cbor
witful native recovery restore --client CLIENT.json --destination BACKEND_UUID --input BACKUP.cbor
witful native migration run --client CLIENT.json --destination BACKEND_UUID --operation OPERATION_UUID
```

A restore alone does not route readers or writers to the destination. Migration
requires equal verified history, drains pending projection, freezes writes and
advances the independently controlled epoch only at cutover. Abort is permitted
only before cutover preparation. After new destination writes, rollback is a new
reverse migration that includes those writes. Never restore an old authority
snapshot over newer accepted data or activate two backend epochs concurrently.

For physical PostgreSQL recovery, retain compatible data and authority frontiers,
continuous WAL, encryption custody and the selected recovery target. Fence old
writers before restoring or promoting a replacement. Validate both registries and
complete acknowledged history, then run the application canary before routing
traffic. A logical `pg_dump` is not a physical base backup or PITR chain; follow
[PostgreSQL's recovery contract](https://www.postgresql.org/docs/current/continuous-archiving.html)
and the selected operator's restore procedure. A synthetic drill establishes only
its measured environment, target, accepted frontier and observed RPO/RTO.

## Binary compatibility checks

The [version-one registry](../tests/native/resources/codec-v1.json) contains exact
CBOR bytes and domain-separated SHA-256 hashes. Both Python tests and the independently
maintained [JavaScript codec](https://github.com/hildjj/cbor2) consume it in CI. Cases
cover signed integer boundaries, byte strings, ordering, nested values and distinct
composed/decomposed Unicode. Rejected inputs include ambiguous forms and unsupported
types. The fixture `$bytes` and `$integer` wrappers belong only to JSON test transport.

The JavaScript checker passes plain `Uint8Array` to its decoder: a Node `Buffer`
retains a JSON conversion hook that can change byte-string re-encoding. Native
version one does not normalize Unicode or silently coerce values. These vectors
establish interoperability for the declared cases, not every possible consumer.
