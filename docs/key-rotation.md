# Collection key rotation

Witful rotates **current managed encrypted files** as one generation and retains
old keys for historical recovery. It does not rewrite Git history, revoke keys,
remove backups, or rotate operating-system, database, or cloud-provider keys.

Old signatures are verified before decryption. Each replacement receives a fresh
content key and nonce, a new signature, and a decrypt-and-compare check. Encryption
and signing identities remain separate. Both signers authenticate a transition
receipt containing public fingerprints and ciphertext digests, never plaintext hashes.

## Inventory and coverage

```bash
witful collection inventory --checkout /path/to/private-copy
```

This reports managed paths and ciphertext hashes; rotation separately verifies all
signatures. Coverage includes the required source bundle, the figure bundle when
present, and every explicitly registered opaque file. Missing files, unknown
encrypted envelopes, orphan sidecars, symlinks, and authentication failures stop
rotation. The inventory is bounded to 256 MiB and 64 additional files.

Inventory journals, audits, exports, indexes, caches and backups before claiming
whole-deployment protection. Arbitrary files are not silently included in the source
archive. Register a reviewed export explicitly, using a non-sensitive identifier:

```bash
witful collection seal-file --checkout /path/to/private-copy \
  --key-dir /protected/current-keys --name export-01 --source /protected/export.bin
witful collection restore-file --checkout /path/to/private-copy \
  --key-dir /protected/current-keys --name export-01 --output /protected/restored.bin
```

Review and commit the envelope, signature, checksum and `.config/collection.json`
together. If an older `collection/.gitignore` excludes the new file namespace,
update it from the maintained collection template or explicitly stage only the
named encrypted envelope and its two sidecars. Never force-add the plaintext
source directory. Inputs are limited to 16 MiB each. Names and counts remain visible.
Use the database's supported backup API to export a live database consistently.
Verify restoration before removing an old copy. Local source files, indexes and
caches continue to require protected working storage; collection rotation does not
replace filesystem or provider key management.

## Prepare and review

Requires the [collection setup tools](private-collections.md#first-setup), the old
key backup and protected local storage. Choose a separate directory and a future
UTC date for the next rotation. These key formats have no built-in expiry.

```bash
witful collection rotation-keys --repo OWNER/REPO \
  --key-dir /protected/next-keys --rotate-by YYYY-MM-DD \
  --output /protected/next-keys.json
witful collection rotate --checkout /path/to/private-copy \
  --key-dir /protected/current-keys --candidate /protected/next-keys.json \
  --output /protected/rotation-review
```

`rotation-keys` explicitly generates or reuses the separate backup and creates a
mode-0600 candidate JSON file. That file includes credentials and passwords: keep
it outside Git, logs and artifact uploads. No secret is uploaded by this command.

`rotate` leaves the active checkout unchanged. Its output contains:

- `previous/`: exact old ciphertext and public metadata, with an old-key-signed
  transition receipt. Every payload is recovered from this backup before cutover.
- `current/`: the complete verified replacement and a new-key-signed transition
  receipt at `collection/rotation.json`.
- `READY`: written only after recovery and unchanged-input checks pass.

A local `READY` marker is not publication. Failed or interrupted candidates lack
that marker. Keep the original active and retry into a new directory. Never publish
partial output. This first rotation policy uses one deadline per generation and
requires replacement of both keys. Reusing either key cannot extend its lifetime;
independent per-key schedules are not implemented.

## CI adoption

Upload the reviewed candidate through stdin and dispatch the trusted workflow:

```bash
gh secret set WITFUL_COLLECTION_NEXT_KEYS --repo OWNER/REPO < /protected/next-keys.json
gh workflow run ci.yml --repo OWNER/REPO --ref main
```

Changing a secret does not trigger Actions. The next main push or explicit dispatch
checks the complete candidate. PRs, tags, other repositories and the public upstream
cannot enter the private collection job. The existing opt-in and branch protection
remain authoritative.

CI rotates every managed payload into protected temporary storage. It retains the
exact decrypt-compared generation in `rotated/`, then renders fresh figures from
current sources into `current/`. This also handles a source update arriving with
a pending rotation. It verifies all output and retains the encrypted
`encrypted-collection-candidate` artifact before publication. Readable figures are
included only when the existing `publish_figures` disclosure setting permits them.

One optimistic GitHub API commit publishes configuration, public keys, envelopes,
signatures and checksums together. The job checks GitHub commit verification and
accepted Git blob identities. A newer main commit or branch protection rejects the
update. It never force-pushes or overrides review. Inspect the remote revision before
retrying an interrupted API request; an uncertain result is not completed rotation.

Automatic requests are limited to 16 MiB including encoding. For larger candidates
or review-protected main, download the artifact, independently restore it using the
new backup, and compare its source revision with current main. Publish **all** files
under `current/` in one signed commit through the normal PR process. Do not split a
key-generation transition into size-ordered commits. Keep `previous/` separately
for recovery alongside `rotated/`, not as current managed files. Artifacts expire under the retention
setting in the workflow; download required recovery material before expiry.

## Promote and retain recovery

Verify the accepted main commit and restore its sources and registered files with
the new backup. Retain old keys and signing pins with the corresponding Git history,
artifacts and backups. A new main commit does not migrate retained copies.

While `WITFUL_COLLECTION_NEXT_KEYS` matches current pins and the deadline, later
runs use it without rotating again. Invalid candidate secrets fail closed. This
also protects against mixing generations during partial primary-secret updates.
From the checkout containing the verified published configuration:

```bash
witful collection promote-keys --checkout /path/to/private-copy --key-dir /protected/next-keys
gh secret delete WITFUL_COLLECTION_NEXT_KEYS --repo OWNER/REPO
gh workflow run ci.yml --repo OWNER/REPO --ref main
```

`promote-keys` verifies current payloads and checks configuration against remote main
before projecting the existing primary secret names. Retry a partial projection
while retaining `NEXT_KEYS`. Clear it only after promotion succeeds, then verify a
refresh using primary secrets. No old backup is deleted automatically. Job-token
commits do not trigger another run, so dispatch explicitly to check adoption.

`rotate_by` blocks new seal, seal-file and refresh writes at the UTC deadline and
prints a reminder within thirty days. Historical restores remain available; an
expired old generation can rotate into a future-dated one. Existing configurations
without a deadline retain their behavior until rotation establishes one. There is
no background scheduler: arrange a dispatch or reminder before expiry if idle.

See [OWASP key management](https://cheatsheetseries.owasp.org/cheatsheets/Key_Management_Cheat_Sheet)
for risk-based rotation and recovery guidance, and
[Cosign verification](https://docs.sigstore.dev/cosign/verifying/verify/) for signature
trust. Routine rotation with retained keys does not revoke a compromised key;
that requires a separate incident and retained-data migration plan.
