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

`deploy/helm/witful` runs bounded one-shot workers (1-16), mounting a source
journal and endpoint from existing Secrets. Repeated workers synchronize the
same immutable source, not independently evolve it. Production uses a managed
PostgreSQL endpoint. The optional single-node database is for development.

Compose is generated from that chart using the pinned
[Composer action](https://github.com/astrivant/composer). Edit chart values and
`deploy/compose.profile.yaml`, regenerate, and review `deploy/compose.yaml`.
Set `WITFUL_DATABASE_URL` and `WITFUL_POSTGRES_PASSWORD` at runtime. Build the
image from this checkout before using the generated local Compose services.
Do not commit credentials or private journal mounts.

The Dockerfile provides development and production targets; the runtime uses a
non-root account. Python tests verify both SQLite and PostgreSQL contracts in
CI. SQLFluff checks the independently stored SQL for each configured dialect.
