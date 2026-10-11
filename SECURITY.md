# Security policy

Report vulnerabilities through [private vulnerability reporting](https://github.com/astrivant/identity/security/advisories/new).
Do not paste personal records, credentials, or private matches into public issues.
The current release line receives security fixes; update before reporting a defect.

## Publication boundary

This project contains code, schemas, and synthetic fixtures. Keep actual lessons,
decisions, prompts, tool-use records, model configuration, and generated personal
graphs in a separately controlled collection. Application users own access and
retention decisions for that collection. Ordinary collection operations do not upload records to a model or telemetry
service. The optional Sapience adapter has an explicit external-processing boundary
described below.

`witful privacy scan` scans tracked and nonignored untracked UTF-8 sources.
`--staged` inspects the complete Git index, so unstaged clean files cannot hide
staged sensitive content. `.git` history and ignored files are outside its scope.
The CI job scans every checked-out source file and must pass before merge/release;
pre-commit exports the same gate as `witful-pii`. Hooks can be bypassed locally,
so repository branch protection must require **PII scan**.

## Additional security gates

The required **Trivy security scan** runs independently in the main pipeline and
blocks releases and private collection refreshes on findings or incomplete scans.
It checks known dependency vulnerabilities and secret patterns; the PII scanner
remains a separate control. Raw findings stay in nonswappable memory, and only
allowlisted metadata is retained. See [scan scope, cache, and PR reporting](docs/security-checks.md).

The private workflow also requires protected working storage and independently
pinned artifact signatures. See [data protection and migration](docs/data-protection.md)
for the exact coverage, readable-figure exception, and unsupported remote-storage
verification. A private repository alone is not encryption.

## What the scanner detects

- Email-like strings, except reserved example.com/org/net, .test, and .invalid domains.
- Personal Unix/macOS/Windows home paths; generic runner/container homes are permitted.
- Common North American phone and US government-ID shapes.
- LinkedIn member profile URLs and PEM/OpenSSH private-key headers.
- Additional case-insensitive literals from `--terms-file` or `WITFUL_PII_TERMS_FILE`.

Keep the terms file outside public source control. Logs contain only relative
file location, line number, and detector ID. A sensitive filename becomes a
digest label. Matched values and snippets are never printed. Files larger than
5 MiB, non-UTF-8/binary files, and unreadable files block the scan; symlink targets
are inspected without following them outside the checkout.

This is a deterministic guard for defined patterns, not an identity classifier.
It cannot recognize all people's names, postal addresses, international phones,
encoded data, photographs, contextual identification, or secrets of every form.
Do not describe a passing scan as proof that a dataset is anonymized. Review
publication contents and use a dedicated secret scanner for broader credentials.
If data reaches Git history or release artifacts, removing the current text is
insufficient: revoke credentials, restrict/delete affected outputs, and assess
history rewriting and registry removal as separate recovery actions.

## Storage and network behavior

JSONL records and Life snapshots contain full supplied text and evidence.
Snapshots intentionally preserve prior records for replay; deleting current
entries does not remove their historical copies. SQLite indexes and plots can
contain the same data. Keep all of these private when they describe people.
Local atomic writes use owner-only files; directory, backup, and Git access
controls remain the operator's responsibility. Journals and indexes remain plaintext to the running application. Managed private
collections require verified filesystem encryption; the low-level standalone library
does not transparently encrypt each local file or attest to a database host.

PostgreSQL is explicit, uses parameterized SQL, and defaults to certificate and hostname verification; explicit URL sslmode overrides are respected.
Use distinct namespaces for logical collections; namespaces do not replace
database authorization or separate roles. Backups and replicas retain data.
Runtime database URLs belong in environment variables or Kubernetes Secrets,
never chart values. Connection errors redact endpoints and credentials.

Registry checks send candidate names to PyPI over HTTPS. The local six-hour
cache retains only name, status, check time, and cooldown, not author metadata.
Avoid confidential names; the cache is disposable. It does not reserve names.

CI runs on synthetic fixtures. PyPI and signing credentials are supplied only
to tag publication jobs. Signing happens after artifact bytes are final; use
the published fingerprint through an independently trusted channel.

## Project checkpoints

Checkpoint JSONL and database mirrors contain project aliases, commit IDs, times,
skill labels, and evidence fingerprints. Generated plots expose those aliases and
counts. They can identify private work even without source text. Do not copy a
private collection into this public repository or cache its database in shared CI
caches. The additive checkpoint table uses the same database trust boundary and
TLS policy as other stores; namespaces are not tenant authorization. The hash
chain checks integrity but is not a signature. See [retention and recovery](docs/checkpoints.md).

## Awareness publication

Awareness is an explicit figure projection, disabled until figure IDs are selected
and `witful awareness push` is invoked. It regenerates plots from current sources,
scans selected SVG text for supported personal-data patterns, and exports only
PNGs, captions, catalog keys, and hashes. Pattern scanning is not OCR or proof of
anonymization. Plot labels can expose project names and relationships even without
journal text. Review the selected plots before publication.

The authenticated GitHub CLI sends the bundle to a dedicated branch in the
configured destination repository and dispatches its immutable commit and hash.
Authentication uses gh's credential store or GH_TOKEN; no token enters the bundle
or CLI output. The API host is fixed to github.com. The receiver must independently
authorize the sender and enable selected figures. SHA-256 detects content changes;
it does not identify a signer. No Cosign signature is added by this command.

The destination data branch and accepted resume inputs persist in Git history.
Disabling future display does not erase earlier figures, PDFs, releases, or CI
artifacts. No source journals, Life snapshots, database files, or local checkout
paths are exported. See [the delivery contract](docs/awareness.md).


## Private collection data handling

Private-copy pipelines are disabled upstream and require both an explicit Actions
variable and a private repository. See [setup and exact secret names](docs/private-collections.md).
Plaintext sources stay under the user's local account; the installer does not
copy full Codex configuration, authentication, browser state, databases, or arbitrary
files. Only the documented source allowlist is serialized. Configurable instructions
are a reviewed text file, not an executable extension.

Each snapshot uses a new random AES-256-GCM key and 96-bit nonce. A dedicated
ssh-keygen-generated RSA-3072 key wraps that key using OAEP with SHA-256. The format,
repository, data purpose, and recipient fingerprint are authenticated context.
Ciphertext is then signed with a separate Cosign key. The recipient verifies the
independently pinned signing fingerprint (local key backup or separate Actions secret) and signature before decrypting, then
validates source contracts and bounded relative paths before rendering. No archive
member can restore credentials, absolute paths, traversal paths, symlinks, or devices.
The 32 MiB plaintext / 16 MiB decoded file budget bounds normal transport processing.

Cosign runs in explicit private-key mode with public transparency upload and signing
configuration services disabled. Verification omits transparency-log inclusion for
these private offline signatures while still requiring the trusted key and signature.
No personal source digest, label, or bundle is intentionally sent to a public
transparency service. These are private key signatures, not publicly logged attestations.

| Boundary | Stored data | Retention and access |
| --- | --- | --- |
| Local managed collection | Journals, reviewed instructions, disposable indexes | Encrypted volume required and checked; owner-only files; backups must also be protected |
| Local key backup | Encrypted RSA and Cosign private keys, passwords, public keys | Separate 0700 directory, 0600 files; retain for recovery, never Git |
| GitHub Actions secrets | Repository-specific keys and passwords | Until explicitly replaced/deleted; accessible to authorized workflow code |
| Git history | Encrypted source and figure envelopes, signatures, checksums, public keys, trust pins, generic README | Repository retention; old revisions remain decryptable with retained keys |
| Actions artifacts | Encrypted figures and verification material only | Seven days by default; repository Actions access controls |
| Actions dependency caches | Virtual environments and tooling | GitHub cache retention; no decrypted collection or key backup |
| Runner temporary storage | Decrypted sources, derived figures, plotting caches | Nonswappable memory filesystem; cleaned on exit and workflow completion; no disk fallback |
| Optional readable figures | SVG labels, counts, concepts, and relationships | Explicit opt-in; plaintext in private Git history, including after later disabling |

Keys and their passwords together permit recovery, so the local backup directory
must be protected as a complete credential. Keys in GitHub secrets protect stored
ciphertext, not against GitHub, authorized administrators, compromised dependencies,
or trusted workflow code that can read those secrets. Only reviewed main-branch code
receives them in the supplied workflow. Malicious code merged to main could exfiltrate
data; retain review controls. Cleanup is not guaranteed secure erasure, especially
after host loss or forced termination. Use fresh hosted runners for this workflow.

The source PII scanner recognizes only the two fixed encrypted-envelope paths and
validates their closed schemas and encoding/size bounds instead of scanning random
ciphertext as text. Signature verification occurs at the collection consumer; a
schema-valid envelope alone does not establish authenticity. Plaintext readable
plots remain subject to the ordinary scanner. Do not use this exception for arbitrary
opaque blobs or conclude that encrypted data is anonymized.

For compromise, disable `WITFUL_COLLECTION_ENABLED`, restrict repository access,
remove exposed artifacts/caches as appropriate, and assess whether an attacker had
both ciphertext and keys. Removing a file from the latest revision cannot revoke old
Git objects or downloads. Rotation requires decrypting with the retained old key,
establishing and independently recording new trust pins, resealing, and replacing
secrets; the installer deliberately refuses silent rotation. Losing all copies of
the private keys and passwords prevents recovery.

## Optional Sapience processing

`witful sapience export` writes plaintext concept text and provenance locally.
`sync` sends those records to the explicitly selected MCP server, which stores
plaintext content, metadata, and embeddings. Sapience uses OpenAI embeddings by
default; configure its local embedding provider before synchronization to avoid
sending concept text to OpenAI. Initial local model installation can download files.
`propose` asks Sapience to send retrieved memories to Anthropic for synthesis.
Provider terms, retention, credentials, and the server's access controls apply.

The adapter launches the selected executable without a shell. It forwards only
its documented provider/storage settings plus the MCP SDK's minimal process
environment. Trust that executable and its Python import path. Namespace checks
avoid accidental ID collisions; they do not provide authentication or tenant isolation.
The private collection's encrypted Git transport does not encrypt Sapience's database.

Generated briefs are plaintext pending-review files under ignored `.witful/proposals/`.
They never update reviewed journals automatically. Review claims and cited source IDs
before recording an accepted lesson. Stable upserts support resuming partial writes;
there is no automatic deletion of remote records removed from a local catalog.
See [Sapience operations and recovery](docs/sapience.md).

## Multisleeving and termination

Sleeves create private branches and linked worktrees. Fetch and push destinations
must identify the same private GitHub repository and are rechecked before writes.
Encrypted collections retain independent plaintext sources outside Git and publish
only the established signed transport. Directly tracked collections retain their
existing plaintext-in-private-Git policy; multisleeving does not encrypt them.

Local receipts include paths, revision identifiers, timestamps, key-directory paths
without key contents, and a plaintext archive digest. They remain under Git's common
directory and are not pushed. `status` prints local metadata; do not publish it as
a public log. Remote branch names and commit summaries must be non-sensitive.

Use durable encrypted volumes for worktrees, the common Git directory, and private
source directories; mount keys separately. The supervisor forwards catchable
signals and saves within a deadline, but SIGKILL, host loss, storage failure, and
unavailable credentials/network can prevent backup. It never marks an unmerged
session closed. Open worktrees, branches, and partial edits are retained for explicit
recovery. Child workloads control their own logs and must join their writers before
exit. See [multisleeving](docs/multisleeving.md) for the lifecycle and residual risks.

## Retrospective reviews

Decision assessments, original context, knowledge snapshots, and proposed lessons
can reveal sensitive work. Reflection sources join the encrypted collection archive;
CI keeps pending plans inside the signed, encrypted figure archive. Upstream examples
contain synthetic data only. Readable plots remain a separate opt-in disclosure.
No model call, lesson acceptance, or external publication occurs automatically when
the review cadence is reached.
