# Identity

[![Python coverage](https://raw.githubusercontent.com/astrivant/identity/gh-pages/badges/coverage.svg)](https://github.com/astrivant/identity/actions/workflows/ci.yml)


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
- [How it works](#how-it-works)
- [Your collection](#your-collection)
  - [Lessons and decisions](#lessons-and-decisions)
  - [Project history and tools](#project-history-and-tools)
  - [Instance evidence](#instance-evidence)
  - [Continual learning](#continual-learning)
  - [Concurrent sessions](#concurrent-sessions)
  - [Optional resume figures](#optional-resume-figures)
- [Integrations and operations](#integrations-and-operations)
  - [Git and GitOps](#git-and-gitops)
  - [Retrieval and storage](#retrieval-and-storage)
  - [Privacy and data protection](#privacy-and-data-protection)
  - [Inputs](#inputs)
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

Use the [agent skill](SKILL.md) to find relevant lessons, record actual applications,
and respect publication boundaries. Start with this prompt:

> Read SKILL.md in this checkout and help me maintain my existing Identity collection using Witful.
> Preserve its configuration, validate the relevant sources, and use the documented
> commands. Create a collection or publish selected figures only when I request it.

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
[Working-context resolution](docs/context.md) reviews the applicable neighborhood and
directed prerequisites before each work step. Its offline CLI is advisory.
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

### Continual learning

Revisit past choices against current knowledge, with a review due every 100 commits
by default. Keep the original constraints fixed, record actual outcomes separately,
and turn useful findings into reviewed lesson proposals. [Configure the cadence and
review workflow](docs/continual-learning.md).

The XY views compare present support for past choices with their outcomes, then
show how circumstances changed afterward. These public previews are **synthetic**;
private collections generate their own figures from reviewed evidence.

[![Past decisions, current knowledge](https://raw.githubusercontent.com/astrivant/identity/gh-pages/badges/continual-learning/decision-outcomes.svg)](docs/continual-learning.md#read-the-figures)

[![What changed afterward](https://raw.githubusercontent.com/astrivant/identity/gh-pages/badges/continual-learning/decision-context.svg)](docs/continual-learning.md#read-the-figures)

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

### Inputs

Collection rotation inputs are documented in [key rotation](docs/key-rotation.md):

| Input | Purpose |
| --- | --- |
| `knowledge/context.json` | Optional reviewed rules and budgets for [working-context resolution](docs/context.md) |
| `collection export --recipient-key` | Optional recipient public PEM; defaults to the operating encryption key, preserving the signer |
| `collection export --output` | Required new encrypted export directory; [defaults and recovery inputs](docs/identity-exports.md#inputs-and-key-lifecycle) |
| `WITFUL_COLLECTION_NEXT_KEYS` | Optional Actions secret containing a complete reviewed candidate generation |
| `.config/collection.json: rotate_by` | UTC deadline for new protected writes; retained historical reads remain available |
| `.config/collection.json: managed_files` | Reviewed opaque files participating alongside source and figure bundles |

See [all collection secrets and permissions](docs/private-collections.md#workflow-and-permissions)
and [CLI inputs](docs/CLI.md) for the remaining configuration.

### Development and releases

[Contributing](CONTRIBUTING.md) covers local checks, measured test coverage,
and reproducible tooling. [Release operations](docs/releases.md) describes signed
artifacts and publication. Detailed package responsibilities live in [Witful's guide](docs/WITFUL.md).
