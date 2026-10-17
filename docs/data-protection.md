# Data protection

Identity's private-collection workflow encrypts underlying records before Git or
artifact publication and authenticates the ciphertext with a separate signing key.
Personal figures and derived data must also be encrypted before publication. Keep
`publish_figures: false`; the local publication gate rejects readable personal
figures even when a legacy configuration enables that option. An end-user can
explicitly decrypt and send a selected figure to a separate destination. Encryption is not a promise that data cannot leak while in use.

## Protection by storage location

| Location | Protection | Verification and limitation |
| --- | --- | --- |
| Private Git snapshots and CI artifacts | AES-256-GCM; RSA-OAEP-wrapped content key; Cosign signature | Independent signing fingerprint checked before decryption; only ciphertext and verification material are uploaded |
| Local managed collection, SQLite indexes, exports, and key backup | Required encrypted filesystem | FileVault on macOS or encrypted block-device ancestry on Linux; unavailable evidence blocks the managed operation |
| CI decrypted sources, render output, caches, and raw Trivy report | Memory filesystem with swap disabled | Host metadata is checked before collection decryption; memory is released after the job |
| Personal graphs in the collection | Encrypted with the collection | Explicit decryption and export is a separate disclosure decision, for example to a resume |
| Remote PostgreSQL storage | Requires separate server-side protection | Managed collections block these operations because the client cannot verify disks, replicas, logs, or backups |
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
prove these properties. Managed collections currently refuse remote database
processing; standalone adapters remain available under their documented operator
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

## Gate local publication

Install both hooks from the project environment:

```bash
pre-commit install --hook-type pre-commit --hook-type pre-push
```

`witful-encrypted-artifacts` checks the complete Git index before committing.
`witful-encrypted-artifacts-push` checks the selected outgoing commit range before
pushing, including intermediate commits and merge parents. Deleting a plaintext
record in a later commit does not make the earlier record safe to publish.
Configuration, envelopes and verification sidecars all come from the same Git
snapshot. Unstaged replacements cannot disguise the bytes being checked.

For a configured encrypted collection, supply its existing independently retained
key backup through each hook's `args`, for example
`args: [--key-dir, /protected/collection-keys]`. This is a location, never key
contents. Repeat `--key-dir` for historical generations in an outgoing range.
The backup must satisfy the existing protected-storage and private-permission
checks. Restore missing keys from the original backup; this command never
creates keys, rotates them, encrypts files, stages changes or modifies history.
Cosign must be installed when encrypted artifacts are present.

```bash
witful collection check-artifacts --staged --key-dir /protected/collection-keys
witful collection check-artifacts --from-ref origin/main --to-ref HEAD \
  --key-dir /protected/collection-keys
witful collection check-artifacts --revision HEAD --key-dir /protected/collection-keys
```

The gate verifies the source bundle, optional encrypted figures, registered opaque
files and their required verification metadata. It checks independent key identity,
signatures, checksums and authenticated decryption. Decrypted payloads remain in
memory; only ciphertext and public verification metadata enter temporary files.
A matching filename, envelope shape or signature alone is insufficient evidence
that a payload is encrypted correctly. Missing keys or invalid artifacts fail the
command with status 2 and redacted diagnostics.

Known collection source records, derived knowledge and runtime state cannot be
published in plaintext through this gate. Readable figures under `docs/collection/`
and configurations enabling `publish_figures: true` are rejected; retain the encrypted figure bundle
and decrypt or export a selected figure only when its owner chooses to share it.
Ordinary public source,
documentation and nested synthetic fixtures require no collection keys. The gate
covers the managed collection namespace, not arbitrary renamed secrets elsewhere
in a repository; keep the PII scanner and existing publication review enabled.

The [pre-commit pre-push integration](https://pre-commit.com/#pre-push) supplies one
selected ref update. Use single-ref pushes with that integration. A native Git hook
can pass its complete stdin to `witful collection check-artifacts --git-pre-push`
plus the same key-directory arguments to check every update, including tags and
new branches. Preserve existing hooks when integrating this command. Native
[pre-push input](https://git-scm.com/docs/githooks#_pre_push) contains all proposed
ref updates; deletion-only updates transfer no new history.

Explicit ranges exclude ancestry already reachable from `--from-ref`. A new ref
without that baseline checks its entire ancestry. History checks require a full
clone and default to at most 1,000 commits; exceeding `--max-commits` refuses the
operation rather than accepting partial coverage. Review the history before
raising that explicit budget. CI runs `--revision HEAD` on the checked-out candidate,
which is a snapshot check, not a claim that existing remote history was migrated.
Local hooks are installable and bypassable, so retain CI and protected-branch gates.

## Migration and retained history

Inventory existing journals, audit records, snapshots, generated JSON, local
indexes, exports, caches, and backups before claiming an existing deployment is
protected. The collection archive has an explicit source allowlist; arbitrary
configuration and custom audit files are not silently included. Preserve and verify
any additional records through a reviewed migration. Make an encrypted backup and
test restoration before removing an old copy.

[Key rotation](key-rotation.md) covers current bundles and explicitly registered
opaque files. Retain old keys for Git history, downloaded artifacts and external
backups. Filesystem and provider keys retain their separate management procedures.

Resealing today's state does not encrypt old Git objects, previous artifacts,
backups, clones, or downloads. History rewriting is a separate coordinated action,
not an automatic installer step. Do not claim an existing private repository was
migrated merely because the library has been upgraded.

See [SECURITY.md](../SECURITY.md) for the complete trust, retention, and incident
boundaries, and [security checks](security-checks.md) for Trivy and PII scanning.
