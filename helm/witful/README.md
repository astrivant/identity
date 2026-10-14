# Witful chart

Run one-shot synchronization workers against an existing PostgreSQL endpoint.
Build and push the application image, prepare the database and source Secrets, then
install this chart. See [deployment and recovery](../../../docs/storage.md).
No credentials or lesson records belong in Helm values. There are no subchart dependencies.

<!-- toc:start -->
**Table of contents**

- [Configuration references](#configuration-references)
- [Configure and install](#configure-and-install)
- [Availability controls](#availability-controls)
- [Parameters](#parameters)
  - [Synchronization workers](#synchronization-workers)
  - [Job lifecycle](#job-lifecycle)
  - [Worker resources and placement](#worker-resources-and-placement)
  - [Development PostgreSQL](#development-postgresql)
<!-- toc:end -->

## Configuration references

See [configuration references](references/README.md) for reviewed overrides with
separate values files, generated input tables, and operating instructions.
The default chart uses an existing PostgreSQL endpoint. The local reference
explicitly enables a disposable single-node database.

## Configure and install

Build an image with the `postgres` extra, then supply existing Secrets. The source
Secret key selected by `source.journalKey` is projected as `lessons.jsonl` under
`/source`; the endpoint Secret key selected by `database.urlKey` contains the full
PostgreSQL URI, including credentials and any explicit TLS options. An optional CA
Secret key selected by `database.caKey` is projected as `root.crt`. Only those source
and CA keys are mounted. Keep credentials and journal contents out of values files.

```bash
helm upgrade --install witful helm/witful \
  --set image.repository=REGISTRY/witful --set-string image.tag=REVIEWED_TAG \
  --set source.existingSecret=reviewed-source,database.existingSecret=database-connection
```

`database.namespace` selects the shared partition. The sync command uses PostgreSQL,
so the local SQLite cache path is unused. The workload always performs `lessons
--repo /source sync`; CLI commands for editing collections are separate operations.
Container paths, the sync command, and disabled service-account token mounting are
fixed chart contracts. Security contexts retain restrictive defaults and can be
adapted for cluster policy. Pod labels cannot override the chart's identity labels.

## Availability controls

Use the [HA reference](references/ha/README.md) for three workers on separate nodes,
zone spread preferences and bounded recovery. `workers` controls parallelism and
completion count for a one-shot Job, not a continuously running replica set.
The chart requires a positive integer and sets no maximum worker count. Kubernetes
API limits, cluster quotas and available capacity still apply; see
[Job parallelism](https://kubernetes.io/docs/concepts/workloads/controllers/job/#controlling-parallelism).
Use `job.suspend` to pause the Job.
Each worker reads the same journal, and PostgreSQL serializes writes; increasing
workers increases redundant attempts rather than write throughput. Database locks
and network round trips are likely constraints; there is no capacity benchmark.
Size CPU and memory for journal parsing and batch size using observed workloads.

Placement, node eligibility, tolerations, priority, retry/deadline budgets,
termination grace and resource requests/limits are exposed below. Native affinity
and the anti-affinity preset are mutually exclusive. Spread constraints without
selectors target this release and Job revision automatically. The development
PostgreSQL remains single-node; choose an external HA endpoint for durable failover.
Jobs use retry/replacement rather than a service PDB, HPA or rollout strategy.

Helm upgrades create a new revision-specific Job. Database identity changes must
also update the connection Secret; initialization variables do not rename an
existing database or user on a retained volume. StorageClass changes require a
separately reviewed volume migration. Changing values does not migrate stored data.

## Parameters

### Synchronization workers

| Name                      | Description                                                                                | Value             |
| ------------------------- | ------------------------------------------------------------------------------------------ | ----------------- |
| `workers`                 | Number of concurrent one-shot sync workers; positive integer with no chart-imposed maximum | `1`               |
| `image.repository`        | Image built from this checkout; publish to a private registry before cluster use           | `witful`          |
| `image.tag`               | Immutable application release or source tag                                                | `0.1.0`           |
| `image.pullPolicy`        | Kubernetes image pull policy                                                               | `IfNotPresent`    |
| `imagePullSecrets`        | Existing registry credential Secret names                                                  | `[]`              |
| `source.existingSecret`   | Secret containing the reviewed journal, mounted read-only                                  | `witful-source`   |
| `source.journalKey`       | Secret key projected as lessons.jsonl                                                      | `lessons.jsonl`   |
| `database.existingSecret` | Secret containing the PostgreSQL URI; never place credentials in values                    | `witful-database` |
| `database.urlKey`         | Key holding the PostgreSQL URI in that Secret                                              | `url`             |
| `database.namespace`      | Shared identity partition; all cooperating workers must use the same value                 | `default`         |
| `database.caSecret`       | Optional Secret containing a private PostgreSQL CA                                         | `""`              |
| `database.caKey`          | Secret key projected as root.crt                                                           | `root.crt`        |

### Job lifecycle

| Name                                | Description                                                 | Value   |
| ----------------------------------- | ----------------------------------------------------------- | ------- |
| `job.suspend`                       | Suspend creation of worker pods                             | `false` |
| `job.terminationGracePeriodSeconds` | Time allowed before Kubernetes forcibly terminates a worker | `30`    |
| `job.backoffLimit`                  | Number of failed pod retries                                | `2`     |
| `job.activeDeadlineSeconds`         | Maximum total job duration                                  | `300`   |
| `job.ttlSecondsAfterFinished`       | Retain completed job status for this many seconds           | `3600`  |

### Worker resources and placement

| Name                                                | Description                                                                           | Value                    |
| --------------------------------------------------- | ------------------------------------------------------------------------------------- | ------------------------ |
| `resources.requests.cpu`                            | Requested worker CPU                                                                  | `100m`                   |
| `resources.requests.memory`                         | Requested worker memory                                                               | `128Mi`                  |
| `resources.limits.cpu`                              | Maximum worker CPU                                                                    | `1`                      |
| `resources.limits.memory`                           | Maximum worker memory                                                                 | `512Mi`                  |
| `scheduling.nodeSelector`                           | Worker node labels required for scheduling                                            | `{}`                     |
| `scheduling.tolerations`                            | Worker pod tolerations                                                                | `[]`                     |
| `scheduling.affinity`                               | Native worker affinity; mutually exclusive with the anti-affinity preset              | `{}`                     |
| `scheduling.podAntiAffinityPreset`                  | Worker separation by topologyKey; empty, soft preference, or hard requirement         | `""`                     |
| `scheduling.topologyKey`                            | Failure domain used by the anti-affinity preset                                       | `kubernetes.io/hostname` |
| `scheduling.topologySpreadConstraints`              | Native spread constraints; omitted selectors default to this release and Job revision | `[]`                     |
| `scheduling.priorityClassName`                      | Existing PriorityClass for worker pods                                                | `""`                     |
| `scheduling.schedulerName`                          | Optional scheduler override                                                           | `""`                     |
| `podLabels`                                         | Additional worker pod labels; chart identity labels are reserved                      | `{}`                     |
| `podAnnotations`                                    | Additional worker pod annotations                                                     | `{}`                     |
| `podSecurityContext`                                | Worker pod security context; defaults to unprivileged execution                       |                          |
| `podSecurityContext.runAsNonRoot`                   | Require non-root worker execution                                                     | `true`                   |
| `podSecurityContext.runAsUser`                      | Worker user ID                                                                        | `10001`                  |
| `podSecurityContext.runAsGroup`                     | Worker group ID                                                                       | `10001`                  |
| `podSecurityContext.fsGroup`                        | Group allowed to read mounted Secrets                                                 | `10001`                  |
| `podSecurityContext.seccompProfile.type`            | Worker seccomp profile                                                                | `RuntimeDefault`         |
| `containerSecurityContext`                          | Worker container security context                                                     |                          |
| `containerSecurityContext.allowPrivilegeEscalation` | Allow privilege escalation in worker containers                                       | `false`                  |
| `containerSecurityContext.readOnlyRootFilesystem`   | Require a read-only worker root filesystem                                            | `true`                   |
| `containerSecurityContext.capabilities.drop`        | Linux capabilities removed from workers                                               | `["ALL"]`                |

### Development PostgreSQL

| Name                                            | Description                                                                             | Value                                                                                          |
| ----------------------------------------------- | --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `postgresql.enabled`                            | Deploy a single-node development database; production should use a managed endpoint     | `false`                                                                                        |
| `postgresql.image`                              | Pinned PostgreSQL development and test image                                            | `postgres:18.6-alpine@sha256:77f585114c32fbca283dc835b0596f4e52b51b4c6662d7810b2f4084f60a1873` |
| `postgresql.existingSecret`                     | Secret with a password key for the development database                                 | `witful-postgres`                                                                              |
| `postgresql.passwordKey`                        | Password key in the development database Secret                                         | `password`                                                                                     |
| `postgresql.database`                           | Development database name; align with the connection URI Secret                         | `witful`                                                                                       |
| `postgresql.username`                           | Development database user; align with the connection URI Secret                         | `witful`                                                                                       |
| `postgresql.storageSize`                        | Persistent data volume capacity                                                         | `1Gi`                                                                                          |
| `postgresql.storageClass`                       | StorageClass name; empty uses the cluster default, a dash disables dynamic provisioning | `""`                                                                                           |
| `postgresql.resources.requests.cpu`             | Requested database CPU                                                                  | `100m`                                                                                         |
| `postgresql.resources.requests.memory`          | Requested database memory                                                               | `128Mi`                                                                                        |
| `postgresql.resources.limits.cpu`               | Maximum database CPU                                                                    | `1`                                                                                            |
| `postgresql.resources.limits.memory`            | Maximum database memory                                                                 | `512Mi`                                                                                        |
| `postgresql.readinessProbe.initialDelaySeconds` | Delay before the first database readiness check                                         | `0`                                                                                            |
| `postgresql.readinessProbe.periodSeconds`       | Interval between database readiness checks                                              | `5`                                                                                            |
| `postgresql.readinessProbe.timeoutSeconds`      | Timeout for each database readiness check                                               | `1`                                                                                            |
| `postgresql.readinessProbe.successThreshold`    | Successes needed to mark the database ready                                             | `1`                                                                                            |
| `postgresql.readinessProbe.failureThreshold`    | Failures needed to mark the database unready                                            | `3`                                                                                            |
| `postgresql.nodeSelector`                       | Development database node selection                                                     | `{}`                                                                                           |
| `postgresql.tolerations`                        | Development database pod tolerations                                                    | `[]`                                                                                           |
| `postgresql.affinity`                           | Development database native pod affinity                                                | `{}`                                                                                           |
| `postgresql.terminationGracePeriodSeconds`      | Development database shutdown grace period                                              | `30`                                                                                           |
