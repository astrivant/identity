# Identity

[![Coverage](https://raw.githubusercontent.com/astrivant/identity/gh-pages/badges/coverage.svg)](https://github.com/astrivant/identity/blob/gh-pages/badges/coverage.json)

Identity is a **user-owned policy and learning layer for intelligent agents**.
It gives engineers and their agents a shared, reviewable record of how to work,
what experience has taught them, and what evidence supports their decisions.
Git preserves that record across projects and agent sessions.

[Witful](docs/WITFUL.md) is the Python library and CLI that manages the collection,
validates its records, and runs its review checks. Agents use those records to guide
execution; people retain authority over accepted guidance and publication.

- **Make every project teach the next.** Capture the work you do, the decisions you
  make, and the lessons worth reusing. Keep the evidence behind your choices within reach.
- **Give your agents a shared understanding of how you work.** Bring reviewed knowledge
  into [agent workflows](SKILL.md) and [MCP-compatible clients through Sapience](docs/sapience.md).
  Run your collection services on [Kubernetes or Docker Compose](docs/storage.md).
- **Let your resume grow with your experience.** Publish selected skill and decision
  figures to [resumeme](https://github.com/astrivant/resumeme) and trigger an automated
  PDF rebuild. [Choose what appears](docs/awareness.md) as your record develops.
- **Keep your data yours.** Own your source records, encrypt and sign
  [private collection snapshots](docs/private-collections.md), and control what
  you share with agents or publish in your resume.

<!-- toc:start -->
**Table of contents**

- [Getting started](#getting-started)
  - [Install Witful](#install-witful)
  - [Create a private identity](#create-a-private-identity)
  - [Work with an AI agent](#work-with-an-ai-agent)
- [Agent chat commands](#agent-chat-commands)
- [Inputs and configuration](#inputs-and-configuration)
- [How it works](#how-it-works)
- [Your collection](#your-collection)
  - [Lessons and decisions](#lessons-and-decisions)
  - [Project history and tools](#project-history-and-tools)
  - [Instance evidence](#instance-evidence)
  - [Concurrent sessions](#concurrent-sessions)
  - [Optional resume figures](#optional-resume-figures)
- [Integrations and operations](#integrations-and-operations)
  - [Git and GitOps](#git-and-gitops)
  - [Retrieval and storage](#retrieval-and-storage)
  - [Privacy and data protection](#privacy-and-data-protection)
  - [Development and releases](#development-and-releases)
<!-- toc:end -->

## Getting started

### Install Witful

Requires Python 3.12+ on macOS or Linux (excluding Python 3.14.1).

```bash
pip install witful
witful --help
```

[Witful](docs/WITFUL.md) provides the collection CLI and Python library.
See [CLI contracts](docs/CLI.md) for commands and their inputs.

### Create a private identity

Keep personal lessons in an independent private copy, with encrypted sources,
signed outputs, and automatic figure refreshes. GitHub public forks cannot be
made private; the installer creates a private copy for you.

Requires Python 3.12+, Git, authenticated `gh`, OpenSSL, `ssh-keygen`, and Cosign
3.x on macOS or Linux:

```bash
gh repo clone astrivant/identity my-identity
cd my-identity
python3 scripts/collection/install.py --repo OWNER/REPO --create
```

Setup preserves existing Codex settings, installs your collection and agent skill
under `~/.codex`, and projects dedicated signing/encryption secrets through `gh`.
Commit the named setup files and push `main`; the first successful refresh replaces
this README with your dashboard and generates your figures. Empty collections start
with empty-state plots. Full figures remain encrypted by default; readable README
plots require a separate opt-in.

Follow [setup, daily sync, and recovery](docs/private-collections.md) for existing
private copies, custom paths, required secrets, and branch protection.
Use [key rotation](docs/key-rotation.md) to replace current encryption and signing
keys while retaining historical recovery.

### Work with an AI agent

For an AI-assisted workflow, read the [agent skill locally](SKILL.md) or
[on GitHub](https://github.com/astrivant/identity/blob/main/SKILL.md). The hosted
copy explains the workflow; collection operations still require an installed
Witful CLI and an explicitly selected local collection. Use this prompt:

> Read SKILL.md in this checkout and help me maintain my existing Identity collection using Witful.
> Preserve its configuration, validate the relevant sources, and use the documented
> commands. Create a collection or publish selected figures only when I request it.

## Agent chat commands

Load [SKILL.md](SKILL.md) for these portable agent conventions. They are chat
instructions, not shell commands. The [command contract](docs/agent-commands.md)
defines scope, review ordering, publication and durable upstream/collection storage.

- `Push`: checked, signed publication of selected work.
  - Alias: `push`.
- `Tag`: release the selected project under its release contract.
  - Alias: `tag`.
- `Tag All`: release explicitly selected active projects.
  - Alias: `tag all`.
- `search soul`: review all applicable standards in the active awareness tree.
  - Alias: `soul search`.
- `project pr rebase`: rebase open PRs safely and return their review order using the [delivery helpers](docs/delivery.md).
  - Aliases: none currently defined.
- `project pr show`: display clickable PRs, dependencies, sizes and CI in review order.
  - Aliases: none currently defined.
- `identity deactivate`: suspend optional collection guidance for this conversation.
  - Aliases: none currently defined.
- `identity activate <name>`: load an existing, explicitly identified collection.
  - Aliases: none currently defined.
- `Lesson: <teaching>`: record a sourced reusable teaching.
  - Alias: `New Lesson: <teaching>`.
- `Insight: <finding>`: record supported evidence under a sourced Lesson.
  - Aliases: `Insight. Record this`, `New insight: <finding>`.
- `Insight -> Lesson`: promote a finding while preserving its history.
  - Aliases: none currently defined.
- `New command: <definition>`: persist a durable command and its aliases.
  - Aliases: none currently defined.

## Inputs and configuration

Commands select an existing collection with `--repo PATH`; the default is the
current directory. An explicit command-line option overrides its corresponding
environment default. Source journals and reviewed configuration stay in the
collection, while local indexes and caches remain outside its published records.

| Input | Default | Purpose |
| --- | --- | --- |
| `--repo PATH` | Current directory | Collection containing `lessons.jsonl` and `knowledge/` sources. |
| `WITFUL_HOME` / `lessons --home PATH` | Current directory's `.witful/` | Local lesson SQLite index; independent of `--repo`. |
| `WITFUL_DATABASE_URL` | Unset, SQLite | PostgreSQL connection URI for lesson indexing and explicitly requested Life/checkpoint mirroring. Treat as a secret. |
| `WITFUL_DATABASE_NAMESPACE` / `--namespace` | `default` | Partition used by cooperating PostgreSQL clients. |
| `WITFUL_PII_TERMS_FILE` / `privacy scan --terms-file` | Unset | Local UTF-8 literal deny terms, one per line; never publish this file. |
| `WITFUL_SAPIENCE_TOKEN` / `sapience --token-env NAME` | Unset | Optional HTTP MCP authentication; the option selects an environment variable name. |
| `CODEX_HOME` / `collection setup --home` | `~/.codex` | Destination for explicitly requested collection setup. |
| `XDG_DATA_HOME` | `~/.local/share` | Default parent for repository-scoped key backups under `witful/collections/`; `collection setup --key-dir` overrides it. |
| `knowledge/catalog.json` | Collection file | Reviewed classification, concepts, and sourced relationships. |
| `knowledge/awareness.json` | Collection file | Optional figure selection and publication configuration. |

| `collection export --recipient-key` | See linked guide | Optional recipient public PEM; defaults to the operating encryption key, preserving the signer |
| `collection export --output` | See linked guide | Required new encrypted export directory; [defaults and recovery inputs](docs/identity-exports.md#inputs-and-key-lifecycle) |
| `WITFUL_COLLECTION_NEXT_KEYS` | See linked guide | Optional Actions secret containing a complete reviewed candidate generation |
| `.config/collection.json: rotate_by` | See linked guide | UTC deadline for new protected writes; retained historical reads remain available |
| `.config/collection.json: managed_files` | See linked guide | Reviewed opaque files participating alongside source and figure bundles |

Collection rotation, expiry and managed-file inputs are detailed in [key rotation](docs/key-rotation.md).

See [CLI options](docs/CLI.md), [database and Helm inputs](docs/storage.md),
[private collection secrets and CI opt-in](docs/private-collections.md), and
[release credentials](docs/releases.md) for operation-specific inputs. Tests alone
use `WITFUL_TEST_DATABASE_URL`; ordinary commands never read that variable.

## How it works

Policy means the reviewed expectations, constraints, and procedures that guide
an agent's work. Learning connects those rules to sourced lessons and observed
outcomes so colleagues can understand why a practice exists and revise it when
new evidence warrants a change.

| Component | Responsibility |
| --- | --- |
| Identity collection | Owns reviewed guidance, lessons, decisions, and their provenance. |
| Witful | Validates and searches records, tracks applications, and checks completion-review coverage. |
| Executing agent | Consults applicable guidance, performs authorized work, and records evidence. |
| Optional Sapience integration | Provides MCP retrieval and generated review proposals from selected records. |

A policy-agent workflow connects these responsibilities: consult guidance, act,
record the outcome, then review the applicable requirements before handoff.
[Completion audits](docs/completion.md) check review coverage against the current
source state. Enforcement depends on the checks installed in the agent's runtime
and delivery pipeline; reviewers still assess whether the evidence supports each
claim. Reading a lesson or installing the package does not grant action authority.

Use Identity to carry engineering practices between projects, explain decisions
to reviewers, and coordinate agents using a versioned body of knowledge. Keep
records in a collection you control, with explicit sharing and publication choices.
[Optional awareness figures](docs/awareness.md) make selected experience visible
in reports and resumes. See [Witful's responsibilities](docs/WITFUL.md#responsibilities)
for the concrete tooling and [Git and GitOps](#git-and-gitops) for the operating model.

## Your collection

### Lessons and decisions

`Identity -> Discipline -> Skill -> Lesson -> Insight` is a composed hierarchy.
Cross-discipline relationships form a separate graph. Recorded applications
measure observed reuse, not intelligence or hidden model reasoning.

Closed schemas generated from attrs models and cattrs conversion validate lesson
and application journals. [Life](docs/CLI.md) preserves explicit
choices, revisions, and the inputs behind their plots. Source snapshots and renderer
drift checks make historical comparisons reviewable.

### Project history and tools

[View the synthetic project-chapter example](docs/assets/project-chapters/checkpoint-transitions.svg).
[Inspect its regeneration and source receipt](docs/view-freshness.md).
[Project checkpoints](docs/checkpoints.md) compare documented learning and skill
use across Git boundaries. The [toolbox and problem taxonomy](docs/CLI.md#toolbox-and-problems)
connect tools to observed work, with source-backed task-frequency plots.

The CLI also includes batched PyPI name checks with TTL caching and rate-limit
cooldowns. See [available commands](docs/CLI.md).

### Instance evidence

[Observed instance tracking](docs/instances.md) connects explicit runtime UUIDs,
authoritative model evidence, definition revisions, and durable task handoffs to
the same native knowledge and Life decision snapshots. Compare skill structure,
insights, lessons, observed use, and decisions across retained boundaries.

**No instance observations ship with this public template.** A new collection
shows an empty-state panel; its first actual observation is a baseline. It never
receives someone else's UUIDs, model history, or invented understanding scores.
The private collection dashboard renders `instance-comparisons` from its own
recorded evidence, including timestamps, revisions, missing evidence, and overlap.

### Concurrent sessions

[Multisleeving](docs/multisleeving.md) gives each instance an isolated branch and
worktree, signed backup checkpoints, and required reconciliation before normal
session closure. A supervised command also attempts a bounded checkpoint on
termination; abrupt process or node loss still requires recovery from saved work.

### Optional resume figures

Awareness figures show the problems you solve, tools and skills you apply, and
recorded decisions that explain your approach. Publish selected figures to
[resumeme](https://github.com/astrivant/resumeme) as an optional resume appendix,
or use them to reflect on your work.

Every figure is opt-in. Counts describe recorded activity, with source evidence;
they are not proficiency scores. See [figure selection and publication](docs/awareness.md).

## Integrations and operations

### Git and GitOps

Git gives your knowledge a versioned history, reviewable changes, and signed
checkpoints. Use branches and pull requests to collaborate; [multisleeving](docs/multisleeving.md)
keeps concurrent instances isolated until their work is reconciled.

Identity fits [GitOps workflows](https://opengitops.dev/): keep desired service
configuration in Git and apply it through your deployment reconciler using the
[Helm deployment](docs/storage.md). Collection CI validates committed inputs and
rebuilds derived dashboards under your [publication policy](docs/private-collections.md).
By default, personal source snapshots and full figures stay encrypted in Git;
readable figures require explicit opt-in.

### Retrieval and storage

[Sapience](docs/sapience.md) adds optional MCP retrieval and generated review
proposals with stable IDs and provenance. Reviewed local journals remain authoritative.

SQLite is the default index and needs no server. Install `witful[postgres]` for the
optional PostgreSQL adapter. See [storage and orchestration](docs/storage.md) for
its operating contract and Kubernetes or Docker Compose deployment.

### Privacy and data protection

Private snapshots are encrypted and signed. Reviewed graphs can remain readable by
explicit choice. Managed collections require encrypted local working storage; CI
uses nonswappable memory for decryption. Read [storage boundaries and migration
requirements](docs/data-protection.md) before using personal records or describing
an existing deployment as encrypted.

Run `witful privacy scan` before sharing a collection. It detects defined patterns
and configured deny terms; it cannot prove text is free of personal data. Trivy
adds dependency-vulnerability and secret checks in CI. See [security checks](docs/security-checks.md)
and [SECURITY.md](SECURITY.md) for publication review and reporting vulnerabilities.

[Signed encrypted exports](docs/identity-exports.md) use the operating key by
default, with an optional recipient public key for sharing. Verify the sender
independently and restore with only the recipient's decryption key.

### Development and releases

[Contributing](CONTRIBUTING.md) covers local checks, measured test coverage,
and reproducible tooling. [Release operations](docs/releases.md) describes signed
artifacts and publication. Detailed package responsibilities live in [Witful's guide](docs/WITFUL.md).
