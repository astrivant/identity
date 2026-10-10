# Identity

[![CI](https://github.com/astrivant/identity/actions/workflows/ci.yml/badge.svg)](https://github.com/astrivant/identity/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/witful)](https://pypi.org/project/witful/)
[![License](https://img.shields.io/github/license/astrivant/identity)](LICENSE)

Build a user-owned record of what you learn, how you solve problems, and where
that knowledge proves useful. Identity connects lessons, skills, decisions, tools,
and project checkpoints so you can review your work and carry useful understanding
into the next project.

[Witful](docs/WITFUL.md) is the Python library and CLI that manages these records.
This repository also provides collection conventions, agent guidance, private-copy
workflows, and optional professional-awareness figures. Public examples are synthetic;
your personal record belongs in your own collection.

<!-- toc:start -->
**Table of contents**

- [Install](#install)
- [Your private identity](#your-private-identity)
- [What Identity records](#what-identity-records)
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

For an AI-assisted workflow, use this prompt:

> Read SKILL.md in this checkout and help me maintain my existing Identity collection using Witful.
> Preserve its configuration, validate the relevant sources, and use the documented
> commands. Create a collection or publish selected figures only when I request it.

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

See [setup, daily sync, and recovery](docs/private-collections.md), including
existing private forks, custom paths, required secrets, and branch protection.

## What Identity records

`Identity -> Discipline -> Skill -> Lesson -> Insight` is a composed hierarchy.
Cross-discipline relationships form a separate graph. Recorded applications
measure observed reuse, not intelligence or hidden model reasoning. Life
preserves explicit choices, revisions, and the inputs behind their plots.

- Closed schemas generated from attrs models, with cattrs conversion.
- Append-only lesson, application, and decision journals with validated IDs.
- Local SQLite or optional PostgreSQL search and decision archive seeding.
- Deterministic plots, source snapshots, and explicit renderer drift checks.
- Project checkpoints comparing documented learning and skill use across Git boundaries.
- A toolbox and problem taxonomy with source-backed task-frequency plots.
- Batched PyPI name checks with TTL caching and rate-limit cooldowns.
- A redacted PII scanner usable locally, in pre-commit, and in CI.
- Opt-in awareness figures and authenticated resume rebuilds through GitHub.

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
