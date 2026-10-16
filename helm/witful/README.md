# Witful chart

Run one-shot synchronization workers, or explicitly enable the protected native
controller profile over an external or operator-managed PostgreSQL data store.
Build and push the application image, prepare the database and source Secrets, then
install this chart. See [deployment and recovery](../../../docs/storage.md).
No credentials or lesson records belong in Helm values. CloudNativePG is a locked,
optional dependency; keep it disabled when your cluster already has an operator.

<!-- toc:start -->

**Table of contents**

- [Configuration references](#configuration-references)
- [Configure and install](#configure-and-install)
- [Availability controls](#availability-controls)
- [Native controller profile](#native-controller-profile)
- [Parameters](#parameters)
  - [Synchronization workers](#synchronization-workers)
  - [Job lifecycle](#job-lifecycle)
  - [Worker resources and placement](#worker-resources-and-placement)
  - [PostgreSQL operator](#postgresql-operator)
  - [Managed PostgreSQL](#managed-postgresql)
  - [Protected native controller](#protected-native-controller)

<!-- toc:end -->

## Configuration references

See [configuration references](references/README.md) for reviewed overrides with
separate values files, generated input tables, and operating instructions.
The default chart uses an existing PostgreSQL endpoint. The local reference
selects one database instance for disposable development; the PostgreSQL reference
uses three operator-managed instances.

## Configure and install

Build an image with the `postgres` extra, then supply existing Secrets. The source
Secret key selected by `source.journalKey` is projected as `lessons.jsonl` under
`/source`; the endpoint Secret key selected by `database.urlKey` contains the full
PostgreSQL URI, including credentials and any explicit TLS options. An optional CA
Secret key selected by `database.caKey` is projected as `root.crt`. Only those source
and CA keys are mounted. Keep credentials and journal contents out of values files.

```bash
bash scripts/chart/dependencies.sh
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
selectors target this release and Job revision automatically. For database HA, use
an external HA endpoint or the [operator-managed reference](references/postgresql/README.md).
`postgresql.spec` accepts the full native CloudNativePG Cluster specification,
including storage classes, placement, replication policy, backups and resources.
`cloudnative-pg` accepts upstream operator chart overrides. Three instances alone
do not guarantee zero data loss; choose replication, backup and recovery policies
for your workload and test them.
Jobs use retry/replacement rather than a service PDB, HPA or rollout strategy.

Helm upgrades create a new revision-specific Job. Database identity changes must
also update the connection Secret; initialization variables do not rename an
existing database or user on a retained volume. Follow the reference migration
procedure before replacing a StatefulSet or changing a storage class. Changing
values does not migrate stored data. A Cluster is retained on Helm deletion by
`helm.sh/resource-policy: keep`; retention is not a backup. Keep its operator and
CRDs available until database recovery or intentional deletion is complete.

## Native controller profile

[The native reference](references/native/README.md) documents stateless controller
HA, complete typed configuration, Secret projections, memory-backed working storage,
network policy, probes and an explicit single-writer Git alternative. It requires
independently administered authority and key services and signed protection evidence.
The default chart remains the read-only synchronization Job. The native profile
validates its ConfigMap from the runtime model; its future CRD design is documented
in the reference without claiming a reconciler is deployed.

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

### PostgreSQL operator

| Name                     | Description                                                                                                | Value   |
| ------------------------ | ---------------------------------------------------------------------------------------------------------- | ------- |
| `cloudnative-pg.enabled` | Install the locked CloudNativePG operator dependency; leave false when the cluster already has an operator | `false` |
| `cloudnative-pg`         | Operator chart overrides; all upstream parameters remain available under this namespace                    |         |

### Managed PostgreSQL

| Name                                             | Description                                                                                                                       | Value                                                                                                                            |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `postgresql.enabled`                             | Create a CloudNativePG Cluster; its CRDs and ready controller must exist before enabling this                                     | `false`                                                                                                                          |
| `postgresql.spec`                                | Native CloudNativePG Cluster spec, validated from the locked dependency CRD; supports the complete upstream configuration surface |                                                                                                                                  |
| `postgresql.spec.instances`                      | PostgreSQL instance count, including the primary; positive integer with no chart-imposed maximum                                  | `3`                                                                                                                              |
| `postgresql.spec.imageName`                      | Operator-compatible PostgreSQL image pinned by OCI digest                                                                         | `ghcr.io/cloudnative-pg/postgresql:18.6-standard-trixie@sha256:c7747d8d1049fff9cf30d9cd83d14d609c957afb5ffbcd114145f393ea1850e1` |
| `postgresql.spec.enableSuperuserAccess`          | Allow external superuser credentials; disabled by default                                                                         | `false`                                                                                                                          |
| `postgresql.spec.bootstrap.initdb.database`      | Application database created on first bootstrap                                                                                   | `witful`                                                                                                                         |
| `postgresql.spec.bootstrap.initdb.owner`         | Application database owner created on first bootstrap                                                                             | `witful`                                                                                                                         |
| `postgresql.spec.bootstrap.initdb.secret.name`   | Existing kubernetes.io/basic-auth Secret with username and password keys; username must match owner                               | `witful-postgres`                                                                                                                |
| `postgresql.spec.storage.size`                   | Persistent storage capacity per PostgreSQL instance                                                                               | `1Gi`                                                                                                                            |
| `postgresql.spec.resources.requests.cpu`         | Requested CPU per database instance                                                                                               | `100m`                                                                                                                           |
| `postgresql.spec.resources.requests.memory`      | Requested memory per database instance                                                                                            | `128Mi`                                                                                                                          |
| `postgresql.spec.resources.limits.cpu`           | CPU limit per database instance                                                                                                   | `1`                                                                                                                              |
| `postgresql.spec.resources.limits.memory`        | Memory limit per database instance                                                                                                | `512Mi`                                                                                                                          |
| `postgresql.spec.affinity.enablePodAntiAffinity` | Spread database instances across eligible nodes                                                                                   | `true`                                                                                                                           |
| `postgresql.spec.affinity.podAntiAffinityType`   | Preferred or required database pod anti-affinity                                                                                  | `preferred`                                                                                                                      |
| `postgresql.spec.affinity.topologyKey`           | Failure domain label used for database separation                                                                                 | `kubernetes.io/hostname`                                                                                                         |
| `postgresql.spec.smartShutdownTimeout`           | Seconds for the operator to wait for client disconnection before fast shutdown                                                    | `30`                                                                                                                             |
| `postgresql.spec.stopDelay`                      | Total seconds allowed for PostgreSQL shutdown before forced termination                                                           | `60`                                                                                                                             |

### Protected native controller

| Name                                                 | Description                                                                                                                            | Value                 |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | --------------------- |
| `controller.enabled`                                 | Deploy the explicit native controller profile instead of the one-shot sync Job                                                         | `false`               |
| `controller.replicas`                                | Stateless PostgreSQL controller replicas; local Git requires exactly one                                                               | `2`                   |
| `controller.configuration`                           | Complete closed native Settings object; validated from the Python model, never credentials or private records                          | `{}`                  |
| `controller.secretEnvironment`                       | Existing Secret key references keyed by authoritative environment variable name                                                        | `{}`                  |
| `controller.archiveVolumes`                          | Existing protected original-Git claims with name, existingClaim, mountPath and readOnly; scoped aliases live in configuration.archives | `[]`                  |
| `controller.secretMounts`                            | Existing Secret projections with name, secretName, mountPath and explicit items; credentials mount read-only                           | `[]`                  |
| `controller.terminationGracePeriodSeconds`           | Pod termination budget; must exceed the configured runtime drain timeout                                                               | `45`                  |
| `controller.workingSizeLimit`                        | Size limit for the memory-backed runtime working directory                                                                             | `256Mi`               |
| `controller.git.existingClaim`                       | Existing retained single-writer Git PVC; never created, formatted or removed by the chart                                              | `""`                  |
| `controller.git.mountPath`                           | Mount path matching configuration.backend.path for local Git                                                                           | `/var/lib/witful/git` |
| `controller.pdb.enabled`                             | Create a PodDisruptionBudget for voluntary maintenance                                                                                 | `true`                |
| `controller.pdb.minAvailable`                        | Minimum available controller pods; use zero for an explicitly reviewed single-writer profile                                           | `1`                   |
| `controller.networkPolicy.enabled`                   | Restrict controller traffic to explicit reviewed peer rules                                                                            | `true`                |
| `controller.networkPolicy.ingress`                   | Native ingress rules for authenticated clients and monitoring; empty denies traffic                                                    | `[]`                  |
| `controller.networkPolicy.egress`                    | Native egress rules for DNS, authority, storage and broker; empty denies traffic                                                       | `[]`                  |
| `controller.probes.startup.failureThreshold`         | Startup attempts before restart                                                                                                        | `30`                  |
| `controller.probes.startup.periodSeconds`            | Startup probe interval                                                                                                                 | `2`                   |
| `controller.probes.readiness.failureThreshold`       | Failed readiness checks before endpoint withdrawal                                                                                     | `3`                   |
| `controller.probes.readiness.periodSeconds`          | Readiness probe interval                                                                                                               | `10`                  |
| `controller.probes.readiness.timeoutSeconds`         | Readiness command time budget                                                                                                          | `6`                   |
| `controller.probes.liveness.failureThreshold`        | Local listener failures before restart                                                                                                 | `3`                   |
| `controller.probes.liveness.periodSeconds`           | Liveness probe interval independent of upstream health                                                                                 | `10`                  |
| `controller.scheduler.enabled`                       | Deploy bounded per-identity delivery CronJobs using only independently scoped client credentials                                       | `false`               |
| `controller.scheduler.schedule`                      | Kubernetes CronJob schedule; the controller also enforces interval and batch policy                                                    | `* * * * *`           |
| `controller.scheduler.seconds`                       | Complete CLI cycle budget in seconds                                                                                                   | `300`                 |
| `controller.scheduler.activeDeadlineSeconds`         | Pod execution deadline; must exceed the CLI cycle budget                                                                               | `330`                 |
| `controller.scheduler.terminationGracePeriodSeconds` | Shutdown budget for the bounded in-flight HTTPS request and interruptible backoff                                                      | `35`                  |
| `controller.scheduler.networkPolicy.enabled`         | Restrict scheduler ingress and explicit controller/DNS egress                                                                          | `true`                |
| `controller.scheduler.networkPolicy.egress`          | Approved scheduler-only network egress rules; empty denies traffic                                                                     | `[]`                  |
| `controller.scheduler.startingDeadlineSeconds`       | Maximum late scheduled-start allowance                                                                                                 | `60`                  |
| `controller.scheduler.successfulJobsHistoryLimit`    | Retained successful scheduling Jobs                                                                                                    | `1`                   |
| `controller.scheduler.failedJobsHistoryLimit`        | Retained failed scheduling Jobs                                                                                                        | `3`                   |
| `controller.scheduler.clients`                       | Identity client Secret references with name, secretName and key; each gets an independent CronJob                                      | `[]`                  |
| `controller.scheduler.secretMounts`                  | Scheduler-only TLS Secret projections; never inherit controller custody/database credentials                                           | `[]`                  |
| `controller.scheduler.resources`                     | Scheduler container resource requests and limits                                                                                       |                       |
| `controller.scheduler.resources.requests.cpu`        | Requested scheduler CPU                                                                                                                | `100m`                |
| `controller.scheduler.resources.requests.memory`     | Requested scheduler memory                                                                                                             | `128Mi`               |
| `controller.scheduler.resources.limits.cpu`          | Maximum scheduler CPU                                                                                                                  | `1`                   |
| `controller.scheduler.resources.limits.memory`       | Maximum scheduler memory                                                                                                               | `512Mi`               |
