# Local development

Enable the chart's single-node PostgreSQL for local Compose development. This
reference is an override of the main chart values; all worker and secret settings
remain inherited. Use a managed database with the default chart for production.

The Composer hook consumes [values.yaml](values.yaml) together with
[the local profile](../../../../services/compose.profile.yaml). Set
`WITFUL_DATABASE_URL` and `WITFUL_POSTGRES_PASSWORD` at runtime, build with
`docker compose -f services/compose.yaml build`, then run
`docker compose -f services/compose.yaml up --abort-on-container-exit --exit-code-from witful`.
Run `docker compose -f services/compose.yaml down -v` to remove the disposable database.
See [storage prerequisites](../../../../docs/storage.md) before mounting a journal.

<!-- toc:start -->
**Table of contents**

- [Parameters](#parameters)
  - [Local development database](#local-development-database)
<!-- toc:end -->

## Parameters

### Local development database

| Name                 | Description                                                      | Value  |
| -------------------- | ---------------------------------------------------------------- | ------ |
| `postgresql.enabled` | Enable the single-node database for disposable local development | `true` |
