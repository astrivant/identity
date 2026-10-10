# Data protection

Identity's private-collection workflow encrypts underlying records before Git or
artifact publication and authenticates the ciphertext with a separate signing key.
Readable figures are an explicit disclosure, even in a private repository. Keep
`publish_figures: false` unless the labels, counts, and relationships are reviewed
for that audience. Encryption is not a promise that data cannot leak while in use.

## Protection by storage location

| Location | Protection | Verification and limitation |
| --- | --- | --- |
| Private Git snapshots and CI artifacts | AES-256-GCM; RSA-OAEP-wrapped content key; Cosign signature | Independent signing fingerprint checked before decryption; only ciphertext and verification material are uploaded |
| Local managed collection, SQLite indexes, exports, and key backup | Required encrypted filesystem | FileVault on macOS or encrypted block-device ancestry on Linux; unavailable evidence blocks the managed operation |
| CI decrypted sources, render output, caches, and raw Trivy report | Memory filesystem with swap disabled | Host metadata is checked before collection decryption; memory is released after the job |
| Reviewed README graphs and selected resume figures | Readable, intentionally published | Labels and relationships remain visible to their audience and in history |
| Remote PostgreSQL or MCP storage | Requires separate server-side protection | Managed collections block these operations because the client cannot verify disks, replicas, logs, or backups |
| Existing standalone collections and old Git history | Existing storage policy | Updating the library does not encrypt or erase historical records; migration is required |

Filesystem encryption protects offline media. An unlocked host, authorized user,
compromised dependency, administrator, or workflow with decryption credentials can
still read records. Public source code and synthetic fixtures do not need to be
hidden. Permissions, hashes, PII detection, and TLS are different controls and do
not establish at-rest encryption. PostgreSQL documents this distinction in its
[encryption options](https://www.postgresql.org/docs/current/encryption-options.html).

## Verify working storage

Use a separate encrypted volume for collections, indexes, key backups, temporary
files, and backups. Check each location before moving real records:

```bash
witful collection check-storage --path /path/to/collection --path /path/to/keys --path /path/to/temp
```

This inspects host metadata; it does not enable FileVault, format disks, or change
mounts. An unsupported platform, container overlay, inaccessible disk utility,
unencrypted mount, or active swap for RAM storage fails closed. Provider-managed
volume encryption invisible to the host is not automatically accepted.

`collection setup` and `restore` mark managed sources with `.witful-protected`.
Ordinary collection CLI commands then recheck source, temporary, and alternate
output locations. Keep `TMPDIR` and plotting caches on protected storage before
starting Python. Direct Python-library calls and manually edited files remain the
caller's responsibility. Do not remove the marker to bypass a failed check.
Standalone `witful init` retains its existing low-level storage contract; it does
not enroll a private collection or establish an encryption guarantee.

For a remote PostgreSQL deployment, independently verify data volumes, tablespaces,
WAL, replicas, snapshots, exports, backups, and key access through the database
operator or hosting provider. A TLS connection and a client-side boolean cannot
prove these properties. Managed collections currently refuse remote database and
MCP processing; standalone adapters remain available under their documented operator
storage contract. Server-side encryption attestation is not implemented.

## Authenticate an encrypted artifact

Retain the signing fingerprint separately from downloaded artifacts. Setup stores
it as `WITFUL_COLLECTION_SIGNING_FINGERPRINT` in Actions secrets. Existing encrypted
installations must rerun setup with their original key directory to install this
additional secret; do not generate a replacement key.

```bash
witful collection verify --checkout /path/to/private-copy --signing-fingerprint TRUSTED_SHA256
witful collection verify --checkout /path/to/private-copy --figures --signing-fingerprint TRUSTED_SHA256
```

Verification rejects a different key, missing/invalid signature, changed ciphertext,
checksum mismatch, or tracked plaintext source records in the publication checkout.
Local restore compares the downloaded signing identity with the retained key backup.
CI compares it with the independently stored Actions secret before decryption and
verifies outputs again before artifact upload. Neither a checksum alone nor a
public key shipped beside an artifact establishes ownership. Signing authenticates
the configured key holder; it does not attest that every source statement is true.

## Migration and retained history

Inventory existing journals, audit records, snapshots, generated JSON, local
indexes, exports, caches, and backups before claiming an existing deployment is
protected. The collection archive has an explicit source allowlist; arbitrary
configuration and custom audit files are not silently included. Preserve and verify
any additional records through a reviewed migration. Make an encrypted backup and
test restoration before removing an old copy.

Resealing today's state does not encrypt old Git objects, previous artifacts,
backups, clones, or downloads. History rewriting is a separate coordinated action,
not an automatic installer step. Do not claim an existing private repository was
migrated merely because the library has been upgraded.

See [SECURITY.md](../SECURITY.md) for the complete trust, retention, and incident
boundaries, and [security checks](security-checks.md) for Trivy and PII scanning.
