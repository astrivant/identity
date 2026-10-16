# Resilient synchronization

Run three copies of one reviewed journal against an external HA PostgreSQL endpoint.
The preset requires three eligible nodes and prefers spreading them across zones.
Each worker repeats the full synchronization; this is a retryable batch Job, not a
continuously available API. The database owns durable state and failover.

<!-- toc:start -->

**Table of contents**

- [Run](#run)
- [Placement and failure recovery](#placement-and-failure-recovery)
- [Parameters](#parameters)
  - [Resilient synchronization](#resilient-synchronization-1)

<!-- toc:end -->

## Run

Prepare the existing source and connection Secrets described in the
[chart guide](../../README.md), and choose an image built from the reviewed source:

```bash
helm upgrade --install witful helm/witful \
  --values helm/witful/references/ha/values.yaml \
  --set sync.image.repository=REGISTRY/witful --set-string sync.image.tag=REVIEWED_TAG
kubectl get jobs,pods -l app.kubernetes.io/instance=witful -o wide
```

Use `kubectl wait --for=condition=complete job/JOB_NAME --timeout=660s` with the
rendered Job name. Inspect failed pod logs and Job conditions if it fails. A chart
upgrade creates a new revision-specific Job. Database credentials stay in Secrets.
Workers cannot independently evolve the journal; PostgreSQL serializes writes
with an advisory lock, so additional workers do not multiply write throughput.

## Placement and failure recovery

Hard node anti-affinity leaves pods Pending when too few nodes are available.
Use `sync.scheduling.podAntiAffinityPreset=soft` to prefer separation while permitting
co-location. The zone spread is a preference, not a guarantee of zone redundancy.
Set native `sync.scheduling.affinity` instead of the preset for custom placement. Spread
selectors default to the release and Job revision; other releases and retained
Jobs do not count toward the generated placement policy.

Retries and the total Job deadline bound recovery. A completed Job stops consuming
resources; it does not keep three workers running. There is no HPA, rolling-update
strategy or PDB for this workload. Kubernetes recommends replacement by the Job
controller for [restartable batch work](https://kubernetes.io/docs/tasks/run-application/configure-pdb/).
Configure availability, backups and failover on the external database separately.
The bundled development database has one replica and is not an HA database.

## Parameters

### Resilient synchronization

| Name                                        | Description                                                                             | Value                    |
| ------------------------------------------- | --------------------------------------------------------------------------------------- | ------------------------ |
| `sync.workers`                              | Concurrent copies of the same immutable journal; requires at least three eligible nodes | `3`                      |
| `sync.scheduling.podAntiAffinityPreset`     | Require each worker in this Job to run on a different node                              | `hard`                   |
| `sync.scheduling.topologyKey`               | Node label used to separate workers                                                     | `kubernetes.io/hostname` |
| `sync.scheduling.topologySpreadConstraints` | Prefer balancing workers across zones; a selector is generated per Job revision         | `[]`                     |
| `sync.job.backoffLimit`                     | Allow replacement attempts after failed workers                                         | `6`                      |
| `sync.job.activeDeadlineSeconds`            | Bound the entire Job, including scheduling, retries and lock contention                 | `600`                    |
| `sync.job.terminationGracePeriodSeconds`    | Allow time for process termination before forced removal                                | `30`                     |
