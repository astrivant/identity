# Witful chart

Run one-shot synchronization workers against an existing PostgreSQL endpoint.
Build and push the application image, prepare the database and source Secrets, then
install this chart. See [deployment and recovery](../../../docs/storage.md).
No credentials or lesson records belong in Helm values. There are no subchart dependencies.

<!-- toc:start -->
**Table of contents**

- [Parameters](#parameters)
  - [Synchronization workers](#synchronization-workers)
  - [Development PostgreSQL](#development-postgresql)
<!-- toc:end -->

## Parameters

### Synchronization workers

| Name                          | Description                                                                      | Value             |
| ----------------------------- | -------------------------------------------------------------------------------- | ----------------- |
| `workers`                     | Number of concurrent one-shot sync workers, from 1 through 16                    | `1`               |
| `image.repository`            | Image built from this checkout; publish to a private registry before cluster use | `witful`          |
| `image.tag`                   | Immutable application release or source tag                                      | `0.1.0`           |
| `image.pullPolicy`            | Kubernetes image pull policy                                                     | `IfNotPresent`    |
| `imagePullSecrets`            | Existing registry credential Secret names                                        | `[]`              |
| `source.existingSecret`       | Secret containing the reviewed lessons.jsonl, mounted read-only                  | `witful-source`   |
| `database.existingSecret`     | Secret containing the PostgreSQL URI; never place credentials in values          | `witful-database` |
| `database.urlKey`             | Key holding the PostgreSQL URI in that Secret                                    | `url`             |
| `database.namespace`          | Shared identity partition; all cooperating workers must use the same value       | `default`         |
| `database.caSecret`           | Optional Secret containing root.crt for a private PostgreSQL CA                  | `""`              |
| `job.backoffLimit`            | Number of failed pod retries                                                     | `2`               |
| `job.activeDeadlineSeconds`   | Maximum total job duration                                                       | `300`             |
| `job.ttlSecondsAfterFinished` | Retain completed job status for this many seconds                                | `3600`            |
| `resources.requests.cpu`      | Requested worker CPU                                                             | `100m`            |
| `resources.requests.memory`   | Requested worker memory                                                          | `128Mi`           |
| `resources.limits.cpu`        | Maximum worker CPU                                                               | `1`               |
| `resources.limits.memory`     | Maximum worker memory                                                            | `512Mi`           |

### Development PostgreSQL

| Name                        | Description                                                                         | Value                                                                                          |
| --------------------------- | ----------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `postgresql.enabled`        | Deploy a single-node development database; production should use a managed endpoint | `false`                                                                                        |
| `postgresql.image`          | Pinned PostgreSQL development and test image                                        | `postgres:18.6-alpine@sha256:77f585114c32fbca283dc835b0596f4e52b51b4c6662d7810b2f4084f60a1873` |
| `postgresql.existingSecret` | Secret with a password key for the development database                             | `witful-postgres`                                                                              |
| `postgresql.storageSize`    | Persistent data volume capacity                                                     | `1Gi`                                                                                          |
