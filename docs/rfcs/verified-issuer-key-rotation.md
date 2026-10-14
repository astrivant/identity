# RFC: Verified-issuer authorization for collection key rotation

Status: proposed, documentation only. No live rotation, credential generation, secret update, trust-anchor installation, deployment, or history rewrite is authorized by this RFC.

## Decision requested

Extend the recoverable rotation mechanism in [PR #15](https://github.com/astrivant/identity/pull/15) with a separately verified authorization layer. A replacement generation may activate only when a scoped authorization statement is signed by an approved rotation authority whose certificate validates to independently provisioned trust anchors, and all possession, freshness, recovery, publication, and workload checks pass.

A valid CA signature establishes a certificate binding under a trust policy. It does not by itself grant permission to rotate this collection. Certificate issuance, workload identity, collection ownership, rotation authorization, data signing, and Git commit signing remain separate decisions.

## Observed baseline

Inspected on 2026-10-14: PR #15 head `18c310aa2d97e7f331e01067d68558ae12cf9d23`, initially against main `e756012a536b996c756895d84a77d352157ccbb8`. PR #15 subsequently merged into main as `ec896fff9e3b28413c1337ce62e02fa8097fb993` at 04:13 UTC. The five reviewed crypto, key-material, rotation, key-generation and publication modules have identical Git blob identities in that merged main. Recheck the baseline before implementation.

The inspected code has three distinct key roles:

- An RSA encryption/recipient key, generated at 3072 bits, wraps a fresh symmetric key using RSA-OAEP-SHA256.
- Each encrypted envelope gets an independent random AES-256-GCM content key and 96-bit nonce. These symmetric keys are not X.509 public keys and must never appear in certificates, receipts, or logs.
- A separate P-256 key, imported into Cosign, signs collection ciphertext. Current verification is offline, pinned-public-key verification; the use of a Sigstore bundle does not mean certificate-based issuer verification is implemented.

See the pinned [key generation](https://github.com/astrivant/identity/blob/18c310aa2d97e7f331e01067d68558ae12cf9d23/pkg/witful/collection/keys.py), [cryptography](https://github.com/astrivant/identity/blob/18c310aa2d97e7f331e01067d68558ae12cf9d23/pkg/witful/collection/crypto.py), [candidate validation](https://github.com/astrivant/identity/blob/18c310aa2d97e7f331e01067d68558ae12cf9d23/pkg/witful/collection/material.py), and [rotation](https://github.com/astrivant/identity/blob/18c310aa2d97e7f331e01067d68558ae12cf9d23/pkg/witful/collection/rotation.py) implementations.

PR #15 accepts one reviewed `WITFUL_COLLECTION_NEXT_KEYS` secret, checks repository, future UTC deadline and private/public pairs, authenticates and restores old snapshots, replaces both long-lived keys, decrypt-compares every managed replacement, and signs identical transition-receipt bytes with both generations. It stages recovery/current snapshots and publishes a complete generation using an optimistic main-head check. Matching candidate keys are adopted idempotently. Old keys remain necessary for retained history.

The inspected implementation does not validate an issuer certificate chain or an authority's rotation role. Receipt verification authenticates bytes and checksum; it does not establish a durable, independent generation high-water mark or fully validate transition ancestry. The authorization described below is additional functionality, not an existing guarantee.

## Scope and threat model

Prevent acceptance of substituted candidates, unauthorized issuers, cross-collection authority reuse, replayed or stale authorizations, validly signed rollback attempts, mixed generations, and partially completed cutovers. Preserve recovery after interruption and explicit access to retained encrypted history.

Assume an attacker may control candidate files, repository contents, downloaded artifacts, network responses, or an otherwise legitimate but unauthorized certificate. A compromised approved authority or workload is a separate incident: limiting roles and lifetimes reduces impact but cannot make that principal trustworthy. An attacker controlling every trust anchor, checkpoint, and verifier is outside this mechanism's protection.

Non-goals: rotate OS/provider/database keys, silently migrate existing installations to keyless signing, rewrite or erase history, promise confidentiality for already stolen ciphertext and keys, or broaden an AI identity's permissions.

## Independent trust policy

Provision an owner-reviewed, versioned rotation policy through the existing trusted setup channel. Do not bootstrap it from an untrusted repository checkout or a candidate's own certificate bundle. The policy contains:

- Stable collection identity and repository identity, destination branch and managed-file scope.
- Explicit allowed CA trust anchors and constrained intermediates, permitted signing algorithms, certificate role/profile and exact authority identity match rules.
- The rotation-authorizer role, distinct from collection data signer and CI publisher. A generic TLS certificate, arbitrary public-Web-PKI root, matching display name, or valid GitHub commit signature grants no rotation authority.
- Approved workload identity and claims: exact issuer, audience, repository identity, workflow identity/ref, environment and event restrictions as applicable. Verify authenticated claims; never use untrusted job environment strings as substitutes.
- Permitted rotation reasons, generation rules, maximum authorization lifetime, clock-skew allowance, deadline limits, revocation freshness, recovery approvals and audit retention.
- A checkpoint authority independent of mutable checkout state. The implementation must choose and document one durable compare-and-set store before enabling automatic activation.

Trust-anchor or role-policy changes require their own owner-authorized transition. A key candidate may not add an anchor that authenticates itself. Routine rotation cannot downgrade policy version, widen scope, or re-enable a denied authority.

## Certificate and issuer verification

Validate the authority leaf through a vetted certificate-path implementation to an explicitly configured anchor. Enforce certificate signatures, validity, algorithm policy, basic constraints, path length, applicable name/policy constraints, critical-extension handling, signing key usage and the selected application role/profile. Match the leaf's authenticated identity to the policy. Record the verified anchor and chain digest, not merely a claimed issuer name. These path-validation concepts come from [RFC 5280](https://www.rfc-editor.org/info/rfc5280/); use its applicable updates and the selected library's supported profile during implementation.

Check revocation through the policy's authenticated, fresh mechanism. New activation fails closed when required status is unavailable, stale, revoked, or unknown. Do not silently accept a certificate because an endpoint timed out. Define short-lived-certificate and offline profiles explicitly rather than assuming either eliminates compromise risk. Bound any certificate-distribution fetch to configured endpoints; untrusted AIA or CRL URLs must not become unrestricted network requests.

The authority certificate authenticates the signer of the authorization statement. Replacement public keys may optionally have purpose-specific certificates, but those certificates do not replace the statement. Bind any supplied replacement certificate's SPKI exactly to the authorized key fingerprint. Keep RSA recipient and data-signing key roles separate.

If a future profile uses Sigstore keyless identity, require both verified identity and OIDC issuer plus the applicable bundle/time/transparency checks. Sigstore's official [verification documentation](https://docs.sigstore.dev/cosign/verifying/verify/) distinguishes identity/issuer verification from public-key verification. The current offline Cosign commands must not be presented as keyless verification. Public transparency upload remains disabled unless its disclosure is separately reviewed and authorized.

## Signed authorization contract

Define a new, closed, versioned `RotationAuthorization` contract. Reject duplicate fields, unknown mandatory versions, ambiguous encodings, invalid sizes and noncanonical signed bytes. Select one canonical encoding and sign those exact domain-separated bytes; an explicitly reviewed JCS profile is an option ([RFC 8785](https://www.rfc-editor.org/info/rfc8785/)). Do not assume existing sorted JSON is automatically JCS-compatible.

The statement binds:

- Domain and schema version; unpredictable transaction ID; policy ID, version and digest.
- Stable collection/repository identity, destination branch, managed-scope digest and purpose `collection-generation-rotation`.
- Exact source commit, previous accepted generation number and receipt digest, old RSA and signing SPKI fingerprints.
- Proposed generation number (exactly previous + 1), replacement RSA and signing SPKI fingerprints, algorithm roles and new rotation deadline.
- Issued-at, not-before and expiry, bounded by policy; approved reason (`scheduled` or separately authorized recovery).
- Expected authenticated workload identity/profile and the authority's scoped role.

No private keys, passwords, bearer/OIDC tokens, raw records, plaintext hashes, or hashes of secret key material belong in this statement. The authority signs public-key identifiers and nonsensitive policy metadata. Public-key fingerprints use SHA-256 over DER SPKI, matching the existing code.

The completed transition receipt additionally binds the authorization digest, verified authority/anchor identifiers, policy decision, source and destination manifests, ciphertext-envelope digests, proof results and recovery verification. Derive receipt identity from immutable final receipt bytes; avoid a self-referential digest. PR #15 puts the new-signer receipt in `current/` and the old-signer copy in `previous/`; its published current snapshot does not by itself carry both signatures. This extension must durably retain both signatures over the exact same receipt bytes in an approved evidence location and verify their receipt/snapshot bindings during activation and recovery. Validate every receipt field against actual snapshots rather than checking signatures alone. Losing the old-signature evidence is an incomplete transition proof, not an implied dual-signature success.

## Proof of possession and content-key handling

Require key-role-appropriate proof before staging is marked verified:

1. The proposed data-signing key signs a domain-separated challenge bound to transaction, collection, source revision and both proposed public-key fingerprints. Verify it under the proposed key. The final new-key receipt signature is additional evidence, not authority to approve its own replacement.
2. The RSA recipient private key must demonstrate successful decryption under the authorized public key. Retain the existing local pair check and decrypt-compare of all managed replacements. For a remote key holder, use a reviewed authenticated challenge/response protocol bound to the same transaction and identity, with a fresh unpredictable challenge and no general decryption oracle. Do not ask an encryption-only key to sign. The exact protocol requires cryptographic review before implementation; [RFC 4211 section 4](https://www.rfc-editor.org/info/rfc4211/) distinguishes signing and encipherment proof and explains transaction/nonce binding.
3. Fresh symmetric content keys stay inside the envelope operation. Bind envelope purpose, recipient, opaque file identifier and generation in a versioned authenticated context for the new format. Bind final envelope digests into the manifest/receipt. Never expose a content key or a secret-key digest as public proof. Successful authenticated decrypt-compare verifies that the intended holder can recover the resulting payload.

Keep legacy envelope decoding for authorized historical reads. Any AAD/schema change requires explicit version migration and substitution tests, not a silent reinterpretation of version 1.

## Replay, rollback and atomic convergence

Use an independently protected durable checkpoint containing collection, policy epoch, accepted generation, receipt digest, accepted commit and any pending transaction. A checkout's signed generation alone cannot detect rollback of the entire checkout.

Activation requires fresh authorization and revocation evidence, correct predecessor, exactly the next generation, source-head equality, and no competing reservation. Reserve the transaction with compare-and-set. The same transaction and digest may resume; conflicting bytes under the same ID fail. An already accepted transaction verifies the accepted result and returns it without performing another rotation.

The checkpoint store and Git are not one transaction. Use recoverable coordination:

1. Validate policy, issuer/role/workload, authorization and possession before obtaining mutation capability.
2. Reserve the next generation against the last durable checkpoint; stage exact previous/current snapshots on protected storage. Authenticate and restore all old data; decrypt-compare all replacements. Produce the receipt and complete manifest.
3. Revalidate authorization freshness, revocation status, policy epoch and source revision immediately before publication. Publish all generation files in one optimistic commit using the existing complete-manifest boundary. Never force-push or bypass review protection.
4. Read back the remote commit and exact file identities. Immediately before checkpoint acceptance, recheck authorization freshness, revocation, current policy and the reservation/fencing epoch. Finalize the checkpoint only for that verified commit and receipt. If authority expires or is revoked after Git publication, keep the outcome pending/quarantined and obtain fresh scoped authorization to activate those exact existing bytes; do not automatically reissue keys or republish. If publication outcome is uncertain, inspect remote state before retrying. If publication succeeded but checkpoint finalization failed, retain the pending reservation, stop further rotations, and reconcile the observed exact commit.
5. Consumers never combine a new configuration with old ciphertext. New writes activate only when commit and accepted checkpoint agree and the workload holds a current-generation fenced capability. Each actual write must reject stale-generation capabilities; acknowledgement or eventual reconciliation alone is insufficient. Offline consumers cannot claim current-generation freshness without a current checkpoint; they may perform explicitly scoped historical reads. Stale writers must reconcile before writing.

Before publication, failures preserve the active generation. After acceptance, do not roll back the checkpoint or silently reactivate old write keys. Restore historical data into protected staging and publish a forward, newly authorized generation when repair is needed. Never delete a recovery snapshot or retire a key as an automatic success side effect.

## Revocation, compromise and retained history

Routine rotation requires old-signer continuity and new-key proof plus issuer authorization. A compromised old signer must not be able to authorize its successor. Lost/compromised old keys use a distinct emergency policy with independent owner/recovery authority approval and an explicit incident receipt; do not silently skip the old-signature requirement.

Revoke compromised authority/workload credentials through separately approved operational procedures, stop new writes where required, and reject pending authorizations from denied principals. Root compromise requires an independent trust-policy recovery path. Cryptographic re-encryption cannot revoke previously downloaded plaintext or repair copies already decryptable with a stolen old key.

Keep old encryption keys in controlled recovery storage while their historical ciphertext must remain accessible; keep public verification keys, chain/status evidence, timestamps and checkpoint/receipt history. Disable old keys for new writes. Expiry of current-use authority must not indiscriminately destroy archival recovery. Historical integrity assessments distinguish a known pre-compromise verified snapshot from a newly presented old-key signature; without trusted time/checkpoint evidence, report uncertainty. Archive access remains separately authorized and must not advance or reset the live checkpoint.

## Dedicated cluster issuer and Git-controller contract

Propose a separately operated in-cluster issuance authority. Git controllers reconcile reviewed desired state and act as authenticated clients; they do not become a CA by virtue of owning Git credentials. Keep the root offline or in appropriately isolated hardware, with a constrained online intermediate where appropriate. Separate CA signing, rotation-authorizer signing, collection-data signing, collection decryption, and workload mTLS keys, even when one service coordinates their lifecycle.

Under an explicitly enabled standing rotation policy, a controller may initiate renewal before the generation deadline or on an authorized revocation event. Schedule with bounded jitter/backoff and enough recovery time; issuer unavailability never extends a deadline or permits an unreviewed key. Track separate states for requested, authorized, custody-ready, backup-verified, staged, published and accepted. Certificate renewal alone neither rotates an encryption generation nor proves backup readiness. Automatic action stays inside the approved collection, reasons, authority and custody profile; changes to those boundaries require new approval.

The service admits a bounded rotation intent only after authenticating the controller and evaluating its repository/collection role. A proposed versioned request carries the transaction ID, immutable desired-state/source revision, policy digest, previous generation/checkpoint, requested key purposes and approved backup profile. Responses expose public certificate chains, public-key fingerprints or opaque backend handles, decision state, receipt digest and stable operation identity. Do not return private keys through Git, controller status, generic tool responses, events or ordinary logs. A controller's retry uses the same transaction identity; an authorization denial is terminal until the underlying approved intent or policy changes.

Use separate least-privilege service accounts for request, issue/authorize, publish, backup and restore. Network and workload admission policies must prevent a controller from escalating into issuer administration or reading other collections' material. The workload's authenticated identity must remain bound to the exact operation; a transport certificate is not a blanket authorization token. General-purpose certificate issuance and arbitrary signing/decryption endpoints are out of scope: expose typed operations with explicit signing purpose, approved payload structure, destination and rate limits.

Availability requires durable quorum-backed issuer state, transaction reservations and fencing tokens that stale leaders cannot reuse. Require the current reservation/fencing epoch at every actual issuance, signing, publication and activation effect; the effect-owning backend must reject stale leader/writer capabilities, including requests admitted before leadership changed. Kubernetes leader election alone is not a cryptographic split-brain guarantee. A partitioned or restored replica must reconcile the authoritative generation/checkpoint and revocation state before serving mutations. Fail closed for new issuance/activation if the required quorum or policy state is unavailable. Preserve a read-only recovery path within its independent authorization scope. Audit replication lag and define the maximum accepted stale-read interval explicitly.

Controllers consume signed, versioned lifecycle events and periodically reconcile against authoritative status; event delivery alone does not establish convergence. On rotation or revocation, identify affected workloads, publish an approved trust overlap if appropriate, require acknowledgement/readback and prevent stale writers from continuing indefinitely. Emergency revocation must not wait for a normal renewal timer. Old certificates/keys may remain useful for historical verification without retaining permission for new requests.

This dependency aligns with the proposed controller/identity boundaries in the product-research RFCs for [polyad identity orchestration](https://github.com/astrivant/product-research/blob/research/theoretical-polyad-identities-20261012/rfcs/theoretical-polyad-identity-orchestration.md), [GitLab repository controllers](https://github.com/astrivant/product-research/blob/research/gitlab-repository-controller-20261013/rfcs/gitlab-repository-controller.md), and [protected identity image compilation](https://github.com/astrivant/product-research/blob/research/protected-identity-image-compiler-20261013/rfcs/protected-identity-image-compiler.md). Those links identify related drafts, not proof that this proposed issuer contract has been implemented or published there.

## Hierarchical backup to 1Password or Vault

Maintain a typed key inventory: parent/issuer reference, public certificate chain, role, collection, generation, algorithm, fingerprint or backend key/version handle, lifecycle status, allowed export profile and recovery dependency. Replicating this hierarchy means preserving verified relationships and recovery metadata. It does not mean automatically copying every private key to every store, nor creating a cryptographic derivation relationship between independent keys.

Choose one explicit custody profile per key:

- **Exportable encrypted-backup profile:** only approved key classes may be exported, wrapped/sealed for a specific recovery recipient and written to a named 1Password vault/item or Vault mount/path. Private-key passwords, wrapping-key recovery and access controls must be designed together; storing a wrapped key and an immediately usable unwrap secret under the same unrestricted principal defeats the intended separation. Verify destination identity and permissions before transfer. Keep versioned backups and exact content/metadata bindings, with readback and isolated restoration tests. Never promote a generation whose required recoverability has not been established.
- **Non-exportable hardware/service profile:** retain handles, versions, public chains, attestation where available and provider-native recovery procedures. Do not claim a raw-key backup to 1Password or Vault exists when the key cannot be exported. Recovery may require supported hardware replication, provider backup or a new key and re-encryption; document the actual guarantee and test it. Do not toggle exportability merely to satisfy a backup request.

Keep collection-source recovery separate from CA/issuer/signing-key recovery. Historical collection ciphertext needs the appropriate old decryption keys and metadata; a CA chain alone cannot decrypt it. Conversely, restoring collection data must not restore an old issuer as an active authority. Back up certificate issuance records, policy epochs, revocations and monotonic checkpoints consistently enough to prevent a restored service from reusing an old generation or forgetting a revoked credential.

Use a narrowly scoped adapter for the selected destination. A 1Password-backed adapter can use the official [1Password SDK](https://www.1password.dev/sdks), but the existing broker has only a verified health-effects surface; its stdio MCP/native mTLS execute/cancel/status transport and Python SDK use do not establish a general key-backup or signing API. Adding those capabilities is a separately reviewed extension with new access scope. Do not repurpose a health operation to transmit key material.

A Vault profile must distinguish secret storage, PKI issuance and cryptographic custody. [Vault Transit](https://developer.hashicorp.com/vault/docs/secrets/transit) provides cryptographic operations and key versioning; it does not store application ciphertext for the caller. Merely naming Vault does not establish retention, backup, sealing or compatibility with the current local-key Cosign/RSA code. Pin and test the selected backend/API profile before migration; maintain an authorized recovery path for retained key versions.

Backup and restore identities need different minimal privileges. Define independent sealing/unsealing recovery, administrative separation, audit redaction, recovery-point/time targets, retention duration and restore-drill frequency. A successful upload or version list is not proof of restorability. Verify the complete chain, key identity, actual required cryptographic operations and historical ciphertext recovery in an isolated authorized environment. Restoration starts quarantined; the current authority checkpoint and revocation state must be reconciled before any issuer becomes active. Retention expiry and deletion remain distinct, explicitly authorized operations.

## Implementation slices and acceptance gates

All items below are proposed work, not changes included with this RFC.

1. Add pure closed contracts and policy validation under `pkg/witful/collection/`, with synthetic fixtures. Introduce a dry-run authorization decision that neither loads live keys nor changes secrets. Preserve `witful.exceptions` ownership and credential-safe diagnostics.
2. Add vetted chain/revocation verification behind explicit adapters. Review dependency choice, certificate profile and current standards/errata; no bespoke PKIX validator. Add independent trust-policy loading and signed-statement verification.
3. Add checkpoint/reservation interface with a tested durable backend; exercise concurrency and crash recovery before enabling publishing. Extend rotation receipt validation and manifest bindings without weakening PR #15's recovery checks.
4. Integrate opt-in authorization gating in `material.py`, `rotation.py`, `pipeline.py` and `publication.py`; extend versioned `models.py`/AAD only after compatibility review. Reject missing authorization when the mode is enabled. Do not silently upgrade existing deployments or replace manual policy with automatic authority.
5. Complete synthetic end-to-end and failure-injection tests, documentation and security review. Only then seek explicit deployment scope for anchor provisioning, key creation/enrollment, persistent access, secret projection and live activation.

Required negative tests: untrusted root; unauthorized but valid leaf; wrong EKU/profile; bad path/critical extension; invalid algorithm; expired/not-yet-valid certificate or statement; revoked/stale/unknown status; issuer/subject/audience/workflow mismatch; cross-repository or scope substitution; key-type/fingerprint mismatch; failed possession; missing predecessor; skipped/repeated generation; replay after acceptance; policy rollback; whole-checkout rollback; concurrent reservations; modified receipt fields; mixed old/new sidecars; envelope/file substitution; interrupted staging; publish timeout before/after acceptance; checkpoint-finalization failure; partial secret promotion; unavailable old keys; emergency recovery without required approval; and successful historical restore after the write deadline without live-state rollback.

Validation must include synthetic RSA/AES/Cosign integration and applicable repository checks documented in [CONTRIBUTING.md](https://github.com/astrivant/identity/blob/18c310aa2d97e7f331e01067d68558ae12cf9d23/CONTRIBUTING.md). Tests must never target real collection secrets. Documentation-only review does not establish runtime security or live rotation success.

## Open decisions before executable work

Choose the authority/CA and exact certificate identity/profile; who provisions/recovers anchors; durable checkpoint backend and readers' freshness policy; precise revocation/offline behavior; reviewed possession protocol for remote key holders; maximum lifetime/skew/deadline policy; emergency approval threshold; privacy-safe retention/location for attestations; issuer quorum/fencing backend; exact controller API; per-key custody/export profiles; verified 1Password/Vault destinations; and backup/restore ownership and guarantees. Until these decisions and implementation scope are reviewed, the safe deliverable is this RFC and test plan.
