# Local development

Select one CloudNativePG instance for disposable Kubernetes development, or use
Composer's explicit local PostgreSQL substitution. The runtime profile selects the
Cluster resource, reads its database/owner, and supplies a pinned vanilla PostgreSQL
image for Compose. Compose does not run the operator or provide failover.

The Composer hook consumes [values.yaml](values.yaml) together with
[the local profile](../../../../services/compose.profile.yaml). Run
`bash scripts/chart/dependencies.sh` first. Set `WITFUL_DATABASE_URL` and
`WITFUL_POSTGRES_PASSWORD` at runtime, build with
`docker compose -f services/compose.yaml build`, then run
`docker compose -f services/compose.yaml up --abort-on-container-exit --exit-code-from witful`.
Run `docker compose -f services/compose.yaml down -v` to remove the disposable database.
See [storage prerequisites](../../../../docs/storage.md) before mounting a journal.

For Kubernetes, an installed CloudNativePG operator must already be ready; follow
[the operator guide](../postgresql/README.md) and substitute this values file for
its three-instance reference. The default reference does not install a second operator.

<!-- toc:start -->
**Table of contents**

- [Parameters](#parameters)
  - [Local development database](#local-development-database)
<!-- toc:end -->

## Parameters

### Local development database

| Name                        | Description                                                                           | Value  |
| --------------------------- | ------------------------------------------------------------------------------------- | ------ |
| `postgresql.enabled`        | Render the CloudNativePG Cluster for local Kubernetes or the explicit Compose mapping | `true` |
| `postgresql.spec.instances` | Use one database instance for disposable local development                            | `1`    |
