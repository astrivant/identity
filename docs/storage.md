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

`helm/witful` runs bounded one-shot workers (1-16), mounting a source
journal and endpoint from existing Secrets. Repeated workers synchronize the
same immutable source, not independently evolve it. Production uses a managed
PostgreSQL endpoint. The optional single-node database is for development.

Compose is generated from that chart using the pinned
[Composer action](https://github.com/astrivant/composer). Edit chart values and
`services/compose.profile.yaml`, regenerate, and review `services/compose.yaml`.
Set `WITFUL_DATABASE_URL` and `WITFUL_POSTGRES_PASSWORD` at runtime. Build the
image from this checkout before using the generated local Compose services.
Do not commit credentials or private journal mounts.

The Dockerfile provides development and production targets; the runtime uses a
non-root account. Python tests verify both SQLite and PostgreSQL contracts in
CI. SQLFluff checks the independently stored SQL for each configured dialect.

Charts live under `helm/`; service configuration and generated Compose files live
under `services/`. The single multi-stage Dockerfile remains at the repository root.
Projects with multiple service images place each Dockerfile under
`services/<service>/Dockerfile`.

The Witful journal-worker chart is separate from the persistent MCP service.
For shared writable memory replicas, use the Sapience fork's controller and chart
as described in [the integration guide](sapience.md#shared-kubernetes-replicas).
