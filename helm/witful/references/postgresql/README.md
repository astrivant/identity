# Operator-managed PostgreSQL

Use CloudNativePG to reconcile PostgreSQL instances, Services, replication and
failover. This reference requires three eligible nodes and persistent storage.
The chart's defaults keep both the operator dependency and Cluster disabled, so
existing external PostgreSQL deployments continue to work.

<!-- toc:start -->

**Table of contents**

- [Install the operator and Cluster](#install-the-operator-and-cluster)
- [Configuration, upgrade and recovery](#configuration-upgrade-and-recovery)
- [Migrate from the former StatefulSet](#migrate-from-the-former-statefulset)
- [Parameters](#parameters)
  - [Operator-managed PostgreSQL](#operator-managed-postgresql-1)

<!-- toc:end -->

## Install the operator and Cluster

Restore the dependency from `Chart.lock` with `bash scripts/chart/dependencies.sh`.
Use Kubernetes compatible with the dependency's `kubeVersion`; see
[upstream installation guidance](https://cloudnative-pg.io/docs/1.30/installation_upgrade/).
Only install one operator for each intended watch scope. Leave `cloudnative-pg.enabled`
false when a platform-managed operator already serves this namespace, and ensure
its CRD/controller version supports the Cluster fields you configure.

For a new operator, install it first with the Cluster disabled. Its chart manages
CRDs as templates, and their admission webhook must be ready before a Cluster is
submitted. A single fresh Helm install with both enabled is not supported here.

```bash
helm upgrade --install witful helm/witful --namespace witful --create-namespace \
  --set cloudnative-pg.enabled=true,postgresql.enabled=false,job.suspend=true
kubectl wait --for=condition=Established crd/clusters.postgresql.cnpg.io --timeout=120s
kubectl rollout status deployment/witful-cloudnative-pg --namespace witful --timeout=180s
```

Prepare `witful-postgres` in that namespace as a `kubernetes.io/basic-auth` Secret
with `username` and `password`; the username must match
`postgresql.spec.bootstrap.initdb.owner`. Supply it through your secret manager.
Do not put passwords in chart values or command arguments. Database/owner settings
apply at first bootstrap. Keep `database.existingSecret` for the separate worker
connection URI and `source.existingSecret` for the reviewed journal.

Create the Cluster while keeping synchronization suspended:

```bash
helm upgrade witful helm/witful --namespace witful \
  -f helm/witful/references/postgresql/values.yaml \
  --set cloudnative-pg.enabled=true,job.suspend=true
kubectl wait --for=condition=Ready cluster/witful-postgres --namespace witful --timeout=600s
```

If reusing a separately installed operator, use `helm upgrade --install` and omit
`cloudnative-pg.enabled=true` instead. Set the worker connection Secret to the
operator's `witful-postgres-rw` Service. Use the full DNS name covered by the
server certificate, configure `sslmode=verify-full`, and project the operator's
`witful-postgres-ca` Secret with `database.caSecret` and `database.caKey=ca.crt`.
When the operator generates an application Secret, it also publishes connection
fields there. This reference supplies an existing credential Secret, so prepare
the worker URI/TLS settings explicitly through your secret manager.

Finally upgrade with the same operator/Cluster overrides, a reviewed application
image, source and connection Secrets, and `job.suspend=false`. Workers are not
automatically blocked until the Cluster is ready; the suspended phase makes that
ordering explicit. `database.namespace` is Witful's data partition, separate from
the Kubernetes namespace.

## Configuration, upgrade and recovery

`postgresql.spec` is the native
[Cluster API](https://cloudnative-pg.io/docs/1.30/cloudnative-pg.v1/), including
placement, storage classes, resources, replicas, synchronous replication, backup
plugins and recovery. Helm's schema is generated from the locked operator CRD;
the running Kubernetes API and controller remain the admission authority.
See [schema provenance](../../THIRD_PARTY.md). Operator chart overrides are passed
under `cloudnative-pg` without a second mapping of its supported fields.

Review upstream compatibility and release notes before changing the dependency
pin. Run `bash scripts/chart/dependencies.sh --update`, regenerate docs/schema and
Compose, then run chart tests and hooks. Upgrade the operator/CRDs before submitting
newly introduced Cluster fields. Keep the database image compatible with the
operator; PostgreSQL major upgrades require the upstream upgrade procedure.

Replication is not a backup. Configure and verify backup/restore, storage encryption
and replication policy before production use. The three-instance reference uses
the upstream default replication policy, not a zero-data-loss promise. The existing
managed-collection remote-storage restrictions still apply; installing an operator
does not establish server-side encryption for Witful.

The Cluster has `helm.sh/resource-policy: keep`, preserving it on Helm removal or
when disabled. If this release owns the operator dependency, uninstalling or
disabling that dependency also removes its controller. Preserve or transfer
controller ownership before retiring the release; do not delete its CRDs while
Clusters remain. Explicitly inspect retained Cluster and PVC ownership during cleanup.

## Migrate from the former StatefulSet

The operator does not adopt a PostgreSQL data directory merely because a release
name or PVC resembles its own. Before upgrading an existing StatefulSet deployment,
make and restore-test a database backup, record PVC names and reclaim policies,
and preserve the old workload/volumes until recovery is verified. Do not run this
chart upgrade against the old database before securing that recovery path: Helm
will remove resources no longer present in its templates.

Create the operator Cluster under a separate Helm release, restore/import the
backup using the supported CloudNativePG procedure, and verify application reads
and synchronization. Switch the worker connection/CA Secrets only after validation.
Keep the old backup and volumes for the reviewed recovery window, then explicitly
retire the old release. No automatic data migration or credential conversion is
performed by this chart.

## Parameters

### Operator-managed PostgreSQL

| Name                                           | Description                                                                                | Value      |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------ | ---------- |
| `postgresql.enabled`                           | Create a PostgreSQL Cluster after the operator is ready                                    | `true`     |
| `postgresql.spec.instances`                    | Primary and replicas; requires at least three eligible nodes                               | `3`        |
| `postgresql.spec.storage.size`                 | Persistent volume capacity per instance; select a StorageClass in your deployment override | `10Gi`     |
| `postgresql.spec.affinity.podAntiAffinityType` | Require separate database nodes                                                            | `required` |
