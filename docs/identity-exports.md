# Signed encrypted identity exports

Export a sealed identity for recovery with its operating keys, or encrypt a copy
for someone else's public key. Witful retains the sender's signing identity in
both cases. Exporting does not rotate keys, change the active collection, activate
another identity, or upload anything.

## Create a copy

Use the installed Witful executable and the same Cosign prerequisite as
[private collection setup](private-collections.md). For an installed collection:

```bash
witful collection export --output /path/to/new-export
```

This uses the checkout and existing key backup recorded in
`$CODEX_HOME/collection/.setup.json` (`~/.codex` by default). To select them explicitly:

```bash
witful collection export \
  --checkout /path/to/my-identity --key-dir /path/to/owner-keys \
  --output /path/to/new-export
```

Export reads **current sealed records**. Seal reviewed local journal changes first
using [Record and synchronize](private-collections.md#record-and-synchronize).
It includes the source archive, the encrypted figure archive when present, and
all registered `managed_files`. Arbitrary configuration, credentials, runtime
databases, caches, Git history and unregistered files are excluded. This is a
current managed snapshot, not a full backup of every file on the machine.
Figures retain their last sealed provenance; export does not regenerate them.

The result is a directory of ciphertext, verification material and a signed
`export.json` manifest. Share the entire directory after reviewing its scope.
No private keys or passwords are included. Existing destinations are rejected;
an interrupted export lacks a valid complete manifest. Retry with a new destination.

## Encrypt for a recipient

Obtain the recipient's trusted RSA public PEM key, at least 3072 bits, through an
authenticated channel. The recipient keeps the corresponding private key and its
password. Override only the encryption recipient:

```bash
witful collection export \
  --recipient-key /path/to/recipient.pub \
  --output /path/to/new-shared-export
```

The recipient key never replaces the operating key or the sender's signer. The
copy uses fresh AES-GCM content keys, wrapped to the selected RSA public key with
OAEP, through the existing [cryptography implementation](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/rsa/).
The sender verifies ciphertext signatures and the complete file inventory before
returning success. With the default key, it additionally decrypts and compares
payloads locally. With a different recipient key, only the recipient can prove
successful decryption; request their restore confirmation before relying on it
as a recovery copy.

This command shares the complete managed selection with whoever controls that
recipient key. Export metadata exposes the repository identity, public-key
fingerprints, opaque file identifiers, ciphertext sizes and digests. Records and
figures remain encrypted, regardless of the collection's `publish_figures` setting.
The export makes no promise about copies a recipient later decrypts or retains.

## Verify and restore

Obtain the sender's SHA-256 signing fingerprint independently, rather than trusting
a fingerprint supplied only inside the same download. Verification needs no private
keys and uses [Cosign blob verification](https://docs.sigstore.dev/cosign/verifying/verify/):

```bash
witful collection verify-export \
  --bundle /path/to/received-export --signing-fingerprint TRUSTED_SENDER_SHA256
```

Restore with the recipient's password-encrypted RSA PEM key and a private file
containing its exact password bytes. Do not put the password on the command line
or append a newline unless that newline is part of the password.

```bash
witful collection restore-export \
  --bundle /path/to/received-export --signing-fingerprint TRUSTED_SENDER_SHA256 \
  --private-key /path/to/recipient.key --password-file /path/to/recipient.password \
  --output /path/to/new-protected-recovery
```

Private inputs require owner-only permissions and
[protected working storage](data-protection.md#verify-working-storage). The output
must be new and outside Git. Witful authenticates an immutable copy of the manifest,
configuration and complete ciphertext set before decrypting. It validates source
records in protected temporary storage before creating the recovery destination.
The result contains `sources/`, optional `figures/`, and `files/` with opaque names.
It does not merge or execute restored instructions. Inspect them before adoption.

Temporary plaintext is cleaned up on normal success/failure; process or machine
failure may leave protected recovery files. Cleanup is not secure erasure of
underlying storage. A failed final write may leave a partial output: retain the
original export and retry into a new destination. Existing records are never
intentionally replaced.

## Inputs and key lifecycle

| Input | Default and contract |
| --- | --- |
| `--output` | Required new directory; encrypted for export, protected plaintext for restore |
| `--checkout` | Installed receipt's checkout, otherwise current working directory |
| `--home` / `CODEX_HOME` | Receipt lookup root; explicit flag wins, then environment, then `~/.codex` |
| `--key-dir` | Existing complete sender backup; explicit path wins over the matching installed receipt |
| `--recipient-key` | Active encryption public key; override takes a trusted RSA public PEM file |
| `--bundle` | Required received export directory for verify/restore |
| `--signing-fingerprint` | Required independently trusted sender pin for verify/restore |
| `--private-key` / `--password-file` | Required recipient-only decryption inputs for restore; no signing private key needed |

Without a selected local backup, export uses the existing collection environment:
`WITFUL_COLLECTION_PRIVATE_KEY`, `WITFUL_COLLECTION_PUBLIC_KEY`,
`WITFUL_COLLECTION_KEY_PASSWORD`, `WITFUL_COLLECTION_SIGNING_FINGERPRINT`,
`COSIGN_PRIVATE_KEY` and `COSIGN_PASSWORD`. If `WITFUL_COLLECTION_NEXT_KEYS` is
present, the existing [active-generation selection](key-rotation.md) applies:
only an already adopted candidate supplies the operating keys. Export never adopts
or uploads a candidate. Invalid inputs fail rather than falling back to another
identity. Local backups must match both configured active fingerprints.

A due `rotate_by` deadline prevents new signed exports, including recipient copies.
Previously signed exports remain readable with their matching retained recipient
keys and trusted sender fingerprints. A recipient override does not renew a key's
lifetime. Retain those keys for the life of shared recovery copies; later operating
key rotation cannot revoke or rewrite an already distributed export.

The versioned manifest schema is available through `witful collection schema`.
Source archives retain the 16 MiB input limit; encrypted payloads retain their
existing transport bounds, and the captured managed snapshot is bounded to 256 MiB.
Exports intentionally reuse these limits rather than invent a second archive format.
