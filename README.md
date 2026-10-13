# Identity

[![Coverage](https://raw.githubusercontent.com/astrivant/identity/gh-pages/badges/coverage.svg)](https://github.com/astrivant/identity/blob/gh-pages/badges/coverage.json)

Identity is a **user-owned policy and learning layer for intelligent agents**.
It gives engineers and their agents a shared, reviewable record of how to work,
what experience has taught them, and what evidence supports their decisions.
Git preserves that record across projects and agent sessions.

[Witful](docs/WITFUL.md) is the Python library and CLI that manages the collection,
validates its records, and runs its review checks. Agents use those records to guide
execution; people retain authority over accepted guidance and publication.

<!-- toc:start -->
**Table of contents**

- [Install](#install)
- [Agent chat commands](#agent-chat-commands)
- [Inputs and configuration](#inputs-and-configuration)
- [How it works](#how-it-works)
- [Your private identity](#your-private-identity)
- [Git and GitOps](#git-and-gitops)
- [What Identity records](#what-identity-records)
- [Instance evidence](#instance-evidence)
- [Optional awareness](#optional-awareness)
- [Tools and integrations](#tools-and-integrations)
- [Privacy and operations](#privacy-and-operations)
<!-- toc:end -->

## Install

Requires Python 3.12+ on macOS or Linux (excluding Python 3.14.1).

```bash
pip install witful
witful --help
```

Use `pip install 'witful[postgres]'` for a shared PostgreSQL index. SQLite is
the default and needs no server. See [Witful installation and capabilities](docs/WITFUL.md) and [CLI contracts](docs/CLI.md).

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
- `project pr rebase`: rebase open PRs safely and return their review order.
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

## Your private identity

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

Run concurrent instances with [multisleeving](docs/multisleeving.md): each gets an
isolated branch/worktree, signed backup checkpoints, and required reconciliation
before normal session closure. A supervised command also saves on termination.

See [setup, daily sync, and recovery](docs/private-collections.md), including
existing private forks, custom paths, required secrets, and branch protection.

## Git and GitOps

Git gives your knowledge a versioned history, reviewable changes, and signed
checkpoints. Use branches and pull requests to collaborate; [multisleeving](docs/multisleeving.md)
keeps concurrent instances isolated until their work is reconciled.

Identity fits [GitOps workflows](https://opengitops.dev/): keep desired service
configuration in Git and apply it through your deployment reconciler using the
[Helm deployment](docs/storage.md). Collection CI validates committed inputs and
rebuilds derived dashboards under your [publication policy](docs/private-collections.md).
By default, personal source snapshots and full figures stay encrypted in Git;
readable figures require explicit opt-in.

## What Identity records

`Identity -> Discipline -> Skill -> Lesson -> Insight` is a composed hierarchy.
Cross-discipline relationships form a separate graph. Recorded applications
measure observed reuse, not intelligence or hidden model reasoning. Life
preserves explicit choices, revisions, and the inputs behind their plots.

- Closed schemas generated from attrs models, with cattrs conversion.
- Append-only lesson, application, and decision journals with validated IDs.
- Local SQLite or optional PostgreSQL search and decision archive seeding.
- Deterministic plots, source snapshots, and explicit renderer drift checks.
- [Project chapters](docs/checkpoints.md): separate evidence checkpoints for every touched project.
  [View the synthetic example](docs/assets/project-chapters/checkpoint-transitions.svg).
- Observed runtime provenance, startup task reconciliation, and native instance comparisons.
- [Completion audits](docs/completion.md) covering every concept through Insights before handoff.
- A toolbox and problem taxonomy with source-backed task-frequency plots.
- Batched PyPI name checks with TTL caching and rate-limit cooldowns.
- A redacted PII scanner usable locally, in pre-commit, and in CI.
- Opt-in awareness figures and authenticated resume rebuilds through GitHub.

## Instance evidence

[Observed instance tracking](docs/instances.md) connects explicit runtime UUIDs,
authoritative model evidence, definition revisions, and durable task handoffs to
the same native knowledge and Life decision snapshots. Compare skill structure,
insights, lessons, observed use, and decisions across retained boundaries.

**No instance observations ship with this public template.** A new collection
shows an empty-state panel; its first actual observation is a baseline. It never
receives someone else's UUIDs, model history, or invented understanding scores.
The private collection dashboard renders `instance-comparisons` from its own
recorded evidence, including timestamps, revisions, missing evidence, and overlap.

## Optional awareness

Awareness figures provide a professional signature of your work: the problems you
solve, tools and skills you apply, and recorded decisions that explain your approach.
They can become an optional resume appendix, making experience and problem-solving
patterns visible as you work with an agent. They also help you reflect on what you
have practiced and what you want to develop next.

Every figure is opt-in. Counts describe recorded activity, with source evidence;
they are not proficiency scores. See [figure selection and publication](docs/awareness.md).

## Tools and integrations

- [Witful](docs/WITFUL.md): the separately documented package and CLI for collection operations.
- [Sapience](docs/sapience.md): optional MCP retrieval and generated review proposals,
  with stable IDs and provenance. Reviewed local journals remain authoritative.
- [Agent skill](SKILL.md): the workflow for finding relevant lessons, recording actual
  applications, and respecting publication boundaries.

## Privacy and operations

Run `witful privacy scan` before sharing a collection. The scanner detects
defined patterns and configured literal deny terms; it cannot prove text is
free of personal data. Review output and publication contents as described in
[SECURITY.md](SECURITY.md).

See [development](CONTRIBUTING.md), [storage and orchestration](docs/storage.md),
[project checkpoints](docs/checkpoints.md), [awareness publication](docs/awareness.md), [releases](docs/releases.md), and [SKILL.md](SKILL.md) for agent-assisted use.
