# Sapience

Turn engineering lessons into a searchable, typed knowledge base. Sapience
connects lessons across disciplines, records where they were applied, and
preserves decisions with replayable evidence. Your records stay in your own
collection; this repository ships reusable code and synthetic examples.

<!-- toc:start -->
**Table of contents**

- [Install](#install)
- [Model](#model)
- [Privacy and operations](#privacy-and-operations)
<!-- toc:end -->

## Install

Requires Python 3.12+ on macOS or Linux (excluding Python 3.14.1).

```bash
pip install sapience
sapience --help
```

Use `pip install 'sapience[postgres]'` for a shared PostgreSQL index. SQLite is
the default and needs no server. See [CLI and first run](docs/CLI.md).

## Model

`Identity -> Discipline -> Skill -> Lesson -> Lemma` is a composed hierarchy.
Cross-discipline relationships form a separate graph. Recorded applications
measure observed reuse, not intelligence or hidden model reasoning. Life
preserves explicit choices, revisions, and the inputs behind their plots.

- Closed schemas generated from attrs models, with cattrs conversion.
- Append-only lesson, application, and decision journals with validated IDs.
- Local SQLite or optional PostgreSQL search and decision archive seeding.
- Deterministic plots, source snapshots, and explicit renderer drift checks.
- A toolbox and problem taxonomy with source-backed task-frequency plots.
- Batched PyPI name checks with TTL caching and rate-limit cooldowns.
- A redacted PII scanner usable locally, in pre-commit, and in CI.

## Privacy and operations

Run `sapience privacy scan` before sharing a collection. The scanner detects
defined patterns and configured literal deny terms; it cannot prove text is
free of personal data. Review output and publication contents as described in
[SECURITY.md](SECURITY.md).

See [development](CONTRIBUTING.md), [storage and orchestration](docs/storage.md),
[releases](docs/releases.md), and [SKILL.md](SKILL.md) for agent-assisted use.
