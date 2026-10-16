# Protected native PostgreSQL controller

This opt-in profile runs two stateless native controllers against separately
administered PostgreSQL data and authority services and an independent key broker.
It replaces the sync Job only when `controller.enabled` is true. It is a deployment
reference, not evidence that a cluster satisfies the security profile.

<!-- toc:start -->
**Table of contents**

- [Prepare and deploy](#prepare-and-deploy)
- [Availability and recovery](#availability-and-recovery)
- [ConfigMap and future CRD](#configmap-and-future-crd)
- [Parameters](#parameters)
  - [Native PostgreSQL reference](#native-postgresql-reference)
<!-- toc:end -->

## Prepare and deploy

Build the production image with `docker build --target production -t REGISTRY/witful:REVIEWED_TAG .`.
Provision data and authority schemas/roles, grants, broker policy, TLS certificates
and independently trusted signing pins before installation. Connection Secrets
must require `sslmode=verify-full`, use non-superuser roles and name different
administration boundaries. The CloudNativePG dependency may manage the data
Cluster; the authority remains separately administered. Existing schemas and
registered backend IDs are never created or migrated by a chart upgrade.

Replace every illustrative UUID, public-key placeholder, endpoint, Secret name and
network selector in [values.yaml](values.yaml). No private key or credential goes
in values. The projection selects explicit Secret keys. Configure independently
signed, unexpired protection evidence covering the exact effective settings,
including any inactive migration destinations and public sharing recipients.
Optional `configuration.recipients` entries bind a public RSA key and independent
fingerprint to one tenant/identity and request-facing alias. Recipients keep their
private keys and offline verification inputs outside this deployment.
`configuration.derivations` separately selects provisioned fork/split scopes and
grants on configured backends. All participants require the same authority service
for atomic publication; neither this chart nor the runtime creates their grants. The runtime rejects missing or
mismatched evidence. See [native storage](../../../../docs/native-storage.md).

```sh
bash scripts/chart/dependencies.sh
helm template witful helm/witful -f reviewed-native-values.yaml
helm upgrade --install witful helm/witful -f reviewed-native-values.yaml \
  --set image.repository=REGISTRY/witful --set-string image.tag=REVIEWED_TAG
```

The network policy is restrictive by default. Use deployment-owned namespace/pod
selectors for approved clients, DNS, broker, data and authority endpoints. TLS
readiness verifies current protection and dependencies; liveness checks only the
local listener. The memory-backed working directory still needs a node policy
that prevents swapping, which the chart cannot establish. Resource limits include
the memory-backed volume and active decrypted working sets.

## Availability and recovery

PostgreSQL deployments can scale controller replicas and runtime workers without
an arbitrary ceiling. Capacity remains bounded by configured admission, object,
traversal, time and memory limits. Spread pods across failure domains and retain
independent database backups and tested restore keys. A PDB covers voluntary
pod disruptions; it does not establish database failover, RPO or RTO.

For local Git, set one replica and one runtime worker, an existing protected and
externally fenced durable claim, and a backend path under its configured mount.
The chart uses Recreate rollout and never creates, formats or deletes the claim.
Use `pdb.minAvailable: 0` if voluntary replacement is intended. Git destinations
also require the single-writer profile. Changing `backend` cannot perform a
migration; use the explicit migration protocol and receipt's new epoch.

## ConfigMap and future CRD

The full configuration is validated from the runtime's typed model and mounted as
one ConfigMap. Its digest is bound into the independent protection evidence.
A future namespaced `IdentityBackend` CR could express desired storage, credential
references, authority and immutable compatibility versions. A reconciler would
validate policy, expose observed generation/readiness and require an explicit
reviewed migration resource for cutover. It must never treat editing a backend
field as permission to copy private data or advance authority. No such CRD or
controller is installed by this chart.

## Parameters

### Native PostgreSQL reference

| Name                                                              | Description                                                                                               | Value                                        |
| ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| `controller.enabled`                                              | Select the opt-in native controller profile                                                               | `true`                                       |
| `controller.replicas`                                             | Stateless controller replicas                                                                             | `2`                                          |
| `controller.configuration.backend.id`                             | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `00000000-0000-4000-8000-000000000001`       |
| `controller.configuration.backend.kind`                           | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `postgres`                                   |
| `controller.configuration.backend.synchronous`                    | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `true`                                       |
| `controller.configuration.broker.url`                             | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `https://broker.keys.svc:8443`               |
| `controller.configuration.broker.ca`                              | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `/etc/broker-tls/ca.pem`                     |
| `controller.configuration.broker.certificate`                     | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `/etc/broker-tls/client.pem`                 |
| `controller.configuration.broker.key`                             | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `/etc/broker-tls/client.key`                 |
| `controller.configuration.broker.wrapping`                        | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `00000000-0000-4000-8000-000000000002`       |
| `controller.configuration.broker.signing`                         | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `00000000-0000-4000-8000-000000000003`       |
| `controller.configuration.broker.authority`                       | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `00000000-0000-4000-8000-000000000004`       |
| `controller.configuration.broker.policy`                          | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `00000000-0000-4000-8000-000000000005`       |
| `controller.configuration.broker.signers`                         | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `[]`                                         |
| `controller.configuration.probe.tenant`                           | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `00000000-0000-4000-8000-000000000006`       |
| `controller.configuration.probe.identity`                         | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `00000000-0000-4000-8000-000000000007`       |
| `controller.configuration.probe.grant`                            | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `00000000-0000-4000-8000-000000000008`       |
| `controller.configuration.probe.task`                             | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `00000000-0000-4000-8000-000000000009`       |
| `controller.configuration.probe.epoch`                            | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `1`                                          |
| `controller.configuration.probe.policy`                           | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `00000000-0000-4000-8000-000000000010`       |
| `controller.configuration.protection.path`                        | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `/etc/protection/evidence.cbor`              |
| `controller.configuration.protection.public`                      | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `REPLACE_WITH_TRUSTED_BASE64_RAW_PUBLIC_KEY` |
| `controller.configuration.protection.fingerprint`                 | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `REPLACE_WITH_INDEPENDENT_SHA256_PIN`        |
| `controller.configuration.tls.certificate`                        | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `/etc/native-tls/server.pem`                 |
| `controller.configuration.tls.key`                                | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `/etc/native-tls/server.key`                 |
| `controller.configuration.tls.ca`                                 | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `/etc/native-tls/ca.pem`                     |
| `controller.configuration.tls.server_name`                        | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `witful-native`                              |
| `controller.configuration.tls.client_certificate`                 | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `/etc/native-tls/probe.pem`                  |
| `controller.configuration.tls.client_key`                         | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `/etc/native-tls/probe.key`                  |
| `controller.configuration.runtime.workers`                        | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `2`                                          |
| `controller.configuration.runtime.threads`                        | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `4`                                          |
| `controller.configuration.runtime.admission`                      | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `4`                                          |
| `controller.configuration.runtime.recovery_admission`             | Reserved recovery/cancellation slots per worker; one additional operational thread is also reserved       | `1`                                          |
| `controller.configuration.runtime.working_directory`              | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `/run/witful`                                |
| `controller.configuration.runtime.graceful_timeout`               | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `30`                                         |
| `controller.configuration.derivations`                            | Explicit independently provisioned fork/split target scopes and grant bindings                            | `[]`                                         |
| `controller.configuration.recipients`                             | Reviewed identity-bound public export recipients; private recipient keys never enter this chart           | `[]`                                         |
| `controller.configuration.budget.revisions`                       | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `4096`                                       |
| `controller.configuration.budget.refs`                            | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `256`                                        |
| `controller.configuration.budget.seconds`                         | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `30`                                         |
| `controller.configuration.budget.bytes`                           | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `67108864`                                   |
| `controller.secretEnvironment.WITFUL_DATABASE_URL.name`           | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `native-data-connection`                     |
| `controller.secretEnvironment.WITFUL_DATABASE_URL.key`            | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `url`                                        |
| `controller.secretEnvironment.WITFUL_AUTHORITY_DATABASE_URL.name` | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `native-authority-connection`                |
| `controller.secretEnvironment.WITFUL_AUTHORITY_DATABASE_URL.key`  | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `url`                                        |
| `controller.secretMounts`                                         | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `[]`                                         |
| `controller.networkPolicy.ingress`                                | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `[]`                                         |
| `controller.networkPolicy.egress`                                 | Reviewed reference input; replace placeholders to match the independently signed deployment configuration | `[]`                                         |
| `scheduling.podAntiAffinityPreset`                                | Place controllers on separate nodes                                                                       | `hard`                                       |
