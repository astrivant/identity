# Storage and orchestration

The JSONL sources own the records. SQLite is a disposable FTS5 index; setting
`WITFUL_DATABASE_URL` explicitly selects PostgreSQL instead. Install the
`postgres` extra for psycopg. `WITFUL_DATABASE_NAMESPACE` defaults to `default`.
`WITFUL_HOME` or `lessons --home PATH` selects the SQLite cache location.

PostgreSQL synchronization adds immutable lessons and rejects ID collisions.
Life's explicit `seed` command inserts a validated journal and its snapshots
transactionally. `life replay --from-database` reads the remote archive.
Connections default to `sslmode=verify-full`. An explicit URL `sslmode`
overrides that default; use `disable` only for local disposable development. Supply the appropriate CA using PostgreSQL's client settings.

`helm/witful` runs a configurable positive number of one-shot workers, mounting a source
journal and endpoint from existing Secrets. Repeated workers synchronize the
same immutable source, not independently evolve it. The chart exposes placement, priority, resources, retry/deadline and termination
controls. See the [complete parameter table](../helm/witful/README.md) and
[HA reference](../helm/witful/references/ha/README.md). PostgreSQL serializes writes
under an advisory lock; redundant workers do not increase write throughput.
Use an external HA PostgreSQL endpoint or enable the chart's CloudNativePG
`Cluster`. Kubernetes PostgreSQL is always operator-managed: the chart contains no
database StatefulSet. The locked operator dependency is optional when an existing
cluster operator owns those CRDs. Follow the
[operator installation and migration guide](../helm/witful/references/postgresql/README.md)
before enabling a Cluster or replacing an existing database.

Compose is generated from that chart using the pinned
[Composer action](https://github.com/astrivant/composer). Edit chart values and
`services/compose.profile.yaml`, regenerate, and review `services/compose.yaml`.
The local profile explicitly substitutes a disposable PostgreSQL container for the
rendered Cluster; it provides no operator reconciliation or HA. The local override is
[helm/witful/references/local/values.yaml](../helm/witful/references/local/values.yaml)
(previously `services/compose.values.yaml`); update any local generator command
that names the old path. Its [reference guide](../helm/witful/references/local/README.md)
documents the generated parameters and local run/cleanup commands.
Set `WITFUL_DATABASE_URL` and `WITFUL_POSTGRES_PASSWORD` at runtime. Build the
image from this checkout before using the generated local Compose services.
Do not commit credentials or private journal mounts.

Both application image targets run as UID/GID 10001 with Tini as PID 1 and a
writable working directory. Follow [container development and verification](containers.md)
to build the production wheel or an editable development CLI. Python tests verify
SQLite and PostgreSQL contracts in CI; SQLFluff checks the stored SQL dialects.

Charts live under `helm/`; service Dockerfiles, configuration and generated Compose
files live under `services/`. The application Dockerfile is
[`services/witful/Dockerfile`](../services/witful/Dockerfile), with the repository
root as its build context. Replace old `docker build --target TARGET .` commands
with `docker build --file services/witful/Dockerfile --target TARGET .`.

## Private working storage

Managed collections require encrypted source, index, output, and temporary volumes.
Their PostgreSQL operations are blocked until server-side encryption can be verified;
TLS alone is insufficient. Standalone adapters retain their existing operator-owned
storage contract. See [data protection](data-protection.md) for supported checks and
backups, migration, and remote-service requirements.
