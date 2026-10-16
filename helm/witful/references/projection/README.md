# Isolated projection gateway

Deploy this profile as a separate Helm release from the native controller. It owns
one remote Git writer, repository-scoped SSH credentials and independently pinned
host keys. It receives the authority database connection and permit-only broker
grants, with no native data-database connection or source volume.

```bash
helm upgrade --install witful-projection helm/witful \
  -f helm/witful/references/projection/values.yaml \
  -f REVIEWED_GATEWAY_VALUES.yaml
```

Replace every synthetic identifier, public pin, endpoint and Secret reference.
The controller's target UUID, scope and exporter attribution must match the gateway
allowlist. Prepare the encrypted readiness probe, then mount it through the reviewed readiness Secret:

```bash
witful native projection probe --client CONTROLLER_CLIENT.json --output envelope.cbor
```

Use separate gateway transport and broker-client Secrets from the controller's
credentials. A shared client certificate could defeat the intended key-grant
separation even when the runtime code uses only permit operations. Give the gateway caller and readiness identities
only native `project` and broker `unwrap` for the separate permit wrapping generation; retain separate
current original-writer `project`/`export` grants. The controller prepares and signs
permits. The gateway cannot sign them or decrypt the identity sidecar.

Keep one replica and one worker with the Recreate strategy. Remote expected-head
checks, exact retry bytes and independent fetch prevent accidental history rewrite;
review old-process fencing and remote access policy before deploying. Configure
explicit DNS, authority, broker and SSH egress plus authenticated controller ingress.
Default empty network rules deny traffic. The memory working-volume limit bounds
Git transfer scratch space. This reference is rendered and schema-tested, not a
production storage attestation.

See [native storage operations](../../../../docs/native-storage.md) for current
implementation status and the independent deployment-evidence contract.

<!-- toc:start -->
**Table of contents**

- [Parameters](#parameters)
  - [Isolated encrypted projection gateway](#isolated-encrypted-projection-gateway)
<!-- toc:end -->

## Parameters

### Isolated encrypted projection gateway

| Name                                                              | Description                                                                                         | Value                                        |
| ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| `controller.enabled`                                              | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `true`                                       |
| `controller.replicas`                                             | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `1`                                          |
| `controller.configuration.backend.id`                             | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `00000000-0000-4000-8000-000000000001`       |
| `controller.configuration.broker.url`                             | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `https://broker.keys.svc:8443`               |
| `controller.configuration.broker.ca`                              | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `/etc/broker-tls/ca.pem`                     |
| `controller.configuration.broker.certificate`                     | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `/etc/broker-tls/client.pem`                 |
| `controller.configuration.broker.key`                             | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `/etc/broker-tls/client.key`                 |
| `controller.configuration.broker.wrapping`                        | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `00000000-0000-4000-8000-000000000025`       |
| `controller.configuration.broker.signing`                         | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `00000000-0000-4000-8000-000000000003`       |
| `controller.configuration.broker.authority`                       | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `00000000-0000-4000-8000-000000000004`       |
| `controller.configuration.broker.policy`                          | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `00000000-0000-4000-8000-000000000005`       |
| `controller.configuration.broker.signers`                         | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `[]`                                         |
| `controller.configuration.probe.tenant`                           | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `00000000-0000-4000-8000-000000000006`       |
| `controller.configuration.probe.identity`                         | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `00000000-0000-4000-8000-000000000007`       |
| `controller.configuration.probe.grant`                            | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `00000000-0000-4000-8000-000000000008`       |
| `controller.configuration.probe.task`                             | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `00000000-0000-4000-8000-000000000009`       |
| `controller.configuration.probe.epoch`                            | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `1`                                          |
| `controller.configuration.probe.policy`                           | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `00000000-0000-4000-8000-000000000010`       |
| `controller.configuration.probe.envelope`                         | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `/etc/projection-probe/envelope.cbor`        |
| `controller.configuration.protection.path`                        | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `/etc/protection/evidence.cbor`              |
| `controller.configuration.protection.public`                      | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `REPLACE_WITH_TRUSTED_BASE64_RAW_PUBLIC_KEY` |
| `controller.configuration.protection.fingerprint`                 | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `REPLACE_WITH_INDEPENDENT_SHA256_PIN`        |
| `controller.configuration.tls.certificate`                        | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `/etc/native-tls/server.pem`                 |
| `controller.configuration.tls.key`                                | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `/etc/native-tls/server.key`                 |
| `controller.configuration.tls.ca`                                 | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `/etc/native-tls/ca.pem`                     |
| `controller.configuration.tls.server_name`                        | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `witful-native`                              |
| `controller.configuration.tls.client_certificate`                 | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `/etc/native-tls/probe.pem`                  |
| `controller.configuration.tls.client_key`                         | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `/etc/native-tls/probe.key`                  |
| `controller.configuration.runtime.workers`                        | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `1`                                          |
| `controller.configuration.runtime.threads`                        | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `4`                                          |
| `controller.configuration.runtime.admission`                      | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `4`                                          |
| `controller.configuration.runtime.recovery_admission`             | Reserved recovery/cancellation slots per worker; one additional operational thread is also reserved | `1`                                          |
| `controller.configuration.runtime.working_directory`              | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `/run/witful`                                |
| `controller.configuration.runtime.graceful_timeout`               | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `30`                                         |
| `controller.configuration.budget.revisions`                       | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `4096`                                       |
| `controller.configuration.budget.refs`                            | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `256`                                        |
| `controller.configuration.budget.seconds`                         | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `30`                                         |
| `controller.configuration.budget.bytes`                           | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `67108864`                                   |
| `controller.configuration.role`                                   | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `projection`                                 |
| `controller.configuration.projection.mode`                        | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `disabled`                                   |
| `controller.configuration.gateway`                                | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `[]`                                         |
| `controller.secretEnvironment.WITFUL_AUTHORITY_DATABASE_URL.name` | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `native-authority-connection`                |
| `controller.secretEnvironment.WITFUL_AUTHORITY_DATABASE_URL.key`  | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `url`                                        |
| `controller.secretMounts`                                         | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `[]`                                         |
| `controller.networkPolicy.enabled`                                | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `true`                                       |
| `controller.networkPolicy.ingress`                                | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `[]`                                         |
| `controller.networkPolicy.egress`                                 | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `[]`                                         |
| `controller.pdb.enabled`                                          | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `true`                                       |
| `controller.pdb.minAvailable`                                     | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `0`                                          |
| `scheduling.podAntiAffinityPreset`                                | Reviewed gateway input; replace placeholders and independently sign the complete configuration      | `hard`                                       |
