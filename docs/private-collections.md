# Private collections and CI

Create an independent **private copy** of this project for personal records.
GitHub does not allow a public fork to become private. A fork of an already
private repository also works when its organization permits it.
[GitHub fork visibility rules](https://docs.github.com/en/pull-requests/reference/forks).
The public library ships no personal collection, and its collection job stays disabled.

For replacement keys, follow [current-file rotation and retained-history recovery](key-rotation.md).

## First setup

Requires protected local working and key-backup volumes, macOS or Linux, Python 3.12+ excluding 3.14.1, Git, `gh`, OpenSSL,
`ssh-keygen`, and Cosign 3.x. Authenticate `gh` for GitHub.com with access to create
the selected repository and manage its Actions secrets and variables. For example,
Homebrew provides `python`, `gh`, `openssl`, and `cosign`; OpenSSH supplies `ssh-keygen`.

```bash
gh repo clone astrivant/identity my-identity
cd my-identity
python3 scripts/collection/install.py --repo OWNER/REPO --create
```

This runs the code from the current checkout. `--create` creates a private
repository, preserves the public clone as `upstream`, and changes `origin` to
`OWNER/REPO`. It never pushes implicitly. For an existing private copy, clone it
and omit `--create`. Repeating setup reuses the deterministic local key directory;
`--key-dir DIRECTORY` selects an existing complete backup. Partial secret uploads
can be retried with the same directory. Setup refuses implicit key rotation.

The installer:

1. Confirms the explicit repository is private.
2. Creates an empty `~/.codex/collection` with no inherited lessons or observations.
3. Installs a discoverable `witful-collection` skill, preserving Codex configuration,
   authentication, other skills, and any existing collection.
4. Generates dedicated RSA encryption and Cosign signing keys, verifies their public
   identities, and uploads repository-scoped Actions secrets through `gh` stdin.
5. Writes trust pins and encrypted seed data, makes `.github/settings.yml` private,
   and enables the `WITFUL_COLLECTION_ENABLED` Actions variable.

`--home` or `CODEX_HOME` selects another Codex home. It must be outside the Git
checkout. If a collection already exists remotely, use `--restore` with its original key
backup as described below; setup never replaces it with an empty one. The bootstrap environment lives
under `.cache/collection-installer`. Its executable is
`.cache/collection-installer/bin/witful`; the local `collection/.setup.json` receipt
records that command and the checkout/key paths for the installed skill.
Restart the agent to discover the new skill. This does not inject every lesson
into prompts or replace existing `developer_instructions`.

Commit only `.config/collection.json`, `collection/`, and `.github/settings.yml`,
then push `main`. **The first successful collection refresh replaces README.md
and generates figures from your collection.** A new collection produces empty-state
plots, not the author's history or invented activity. Later source commits repeat
that refresh. Configure GitHub Actions to permit this repository's workflow if
organization policy or fork defaults disable it.

## Concurrent instances

Use [multisleeving](multisleeving.md) for concurrent agents. Start each instance
before its first edit, use its isolated source path, checkpoint every coherent
update, and require `sleeve finish` plus `sleeve guard` before normal closure.
The installer's shared plaintext collection is for one writer; do not point
multiple sleeves at it. Each encrypted sleeve restores its own snapshot and
publishes only signed ciphertext. Main CI continues to generate the shared figures.

## Record and synchronize

Use the installed executable (`witful` below) for ordinary lesson, application,
Life, repertoire, and checkpoint commands. The local collection is readable by the running application on a verified encrypted
working volume. See [working storage checks](data-protection.md#verify-working-storage). Its nested `.gitignore` excludes all its contents from a
surrounding checkout; never force-add them.

```bash
witful lessons --repo "$HOME/.codex/collection" add --topic Testing --lesson 'Validate contracts.' --source 'Team review'
witful collection seal --checkout /path/to/my-identity --source "$HOME/.codex/collection" --key-dir /path/to/keys
```

Review and commit `collection/sources.enc.json`, its `.sigstore.json` signature,
and `.sha256` checksum, then push. The managed `collection/.gitignore` limits
ordinary staging to encrypted transport files and public verification material. `seal` validates all supported journals, takes
the current snapshot, encrypts it, signs the ciphertext, and verifies the signature
before replacing those files. It does not push, rotate keys, capture other files,
or publish awareness figures to another repository. No plaintext fallback exists.

The allowlist includes lessons, catalog, applications, Life decisions and their
saved snapshots, repertoire, tool uses, checkpoints, generated source schemas,
and optional `instructions.md`. Put reviewed portable prose in `instructions.md`;
full Codex TOML, credentials, browser state, SQLite files, and arbitrary dotfiles
are deliberately excluded. Active model settings are not automatically imported.

## Figures and README

`.config/collection.json` is a closed schema generated by
`witful collection schema`. Setup fills its repository and key fingerprints.
Preserve those pins when editing `publish_figures`:

- `false` (default): source records **and full figures stay encrypted**. README
  displays the repository's CI badge, the source ciphertext digest, and restore
  instructions. GitHub cannot render encrypted image bytes inline.
- `true`: CI also commits the generated readable SVG figures under `docs/collection/`
  and embeds them in README. This exposes labels, concepts, counts, and relationships
  to repository readers and Git history. A privacy scan checks known text patterns;
  it is not an anonymization guarantee. Review your labels before opting in.

Turning the setting off removes current readable plots on the next successful
refresh. It cannot erase older commits or previously downloaded files. Encrypted
figures remain available in Git and in the seven-day Actions artifact. There is
no decrypted data cache and no public Pages publication in this workflow.

## Recover on another machine

Clone your private repository and recover its key backup through a separate secure
channel. Do not download or print GitHub secrets. From that checkout, run:

```bash
python3 scripts/collection/install.py --repo OWNER/REPO --key-dir /path/to/keys --restore
# Use the installed command path printed in collection/.setup.json for later operations.
witful collection restore --checkout /path/to/my-identity --key-dir /path/to/keys --output /path/to/new-plots --figures
```

Restore requires a new destination. Compare the signing and encryption fingerprints
in `.config/collection.json` with your independently retained setup record before
trusting a cloned repository. A public key supplied beside an artifact is not
an independent trust source. Figures include encrypted `provenance.json`, binding
their source ciphertext digest and source commit. SHA-256 sidecars aid inspection;
Cosign signatures and authenticated encryption provide verification.

## Workflow and permissions

The existing `ci.yml` starts source tests, lint, PII checks, distributions, and
orchestration independently. The private refresh runs after tests/lint/PII pass,
only on `main` pushes or explicit `workflow_dispatch`, with the opt-in variable
and private repository event flag. It verifies live repository visibility again
before decryption. PRs, tags, the public upstream, and disabled copies never receive
collection secrets through this job. PyPI publication is restricted to upstream.

The refresh verifies the pinned signing key, decrypts a bounded source snapshot
into runner-local temporary storage, validates it, regenerates all views, encrypts
and signs them, and updates README. Encrypted outputs, verification metadata, and any explicitly approved readable figures
enter the artifact store. `GITHUB_TOKEN` publishes a verified complete candidate with an optimistic GitHub API commit;
its push does not start another workflow. A newer `main` revision or branch protection
causes a visible push failure, never a force push. Retrieve the encrypted artifact
and integrate it through your repository's review process, or explicitly allow
an authorized automation identity to update generated outputs. Setup does not
weaken branch protection.

The variable `WITFUL_COLLECTION_ENABLED=false` disables refreshes. The required
repository Actions secrets are:

| Secret | Contents |
| --- | --- |
| `WITFUL_COLLECTION_PRIVATE_KEY` | Password-encrypted dedicated RSA PEM key |
| `WITFUL_COLLECTION_PUBLIC_KEY` | Matching RSA PEM public key |
| `WITFUL_COLLECTION_KEY_PASSWORD` | Exact RSA private-key password |
| `WITFUL_COLLECTION_SIGNING_FINGERPRINT` | Independently retained SHA-256 signing public-key fingerprint |
| `WITFUL_COLLECTION_SIGNING_KEY` | Password-encrypted Cosign private key |
| `WITFUL_COLLECTION_SIGNING_PASSWORD` | Exact Cosign key password |
| `WITFUL_COLLECTION_NEXT_KEYS` | Optional complete candidate JSON from `rotation-keys`, with a future rotation deadline |

No new GitHub token is generated; setup uses the authenticated `gh` client and CI
uses the job token. See [data handling and threat boundaries](../SECURITY.md#private-collection-data-handling).


## Instance continuity

The encrypted source allowlist retains `knowledge/instances.jsonl` and its native
`knowledge/snapshots/` references. Sleeve source fingerprints therefore include
durable instance/task handoffs. Divergent journals require reviewed reconciliation;
never choose one side or rewrite their causal history. Collection refresh renders
`instance-comparisons`, with an honest empty state before observations exist.
Readable-figure opt-in applies to these labels too. Exported private OTLP logs and
full instance JSON chart exports are not additional encrypted source inputs.
See [instance provenance and startup reconciliation](instances.md).

## Managed remote storage

Managed collection remote database and MCP operations now fail closed because the
client cannot verify those services' at-rest protection. See the
[protection contract and migration steps](data-protection.md).
