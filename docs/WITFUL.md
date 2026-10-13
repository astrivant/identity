# Witful

Witful is the Python library and CLI for [Identity](https://github.com/astrivant/identity),
a user-owned policy and learning layer for intelligent agents. It turns reviewed
guidance, sourced lessons, and observed decisions into validated, searchable records
that engineers and agents can reuse across projects.

Witful supplies the collection and review tooling. The executing agent applies
relevant guidance within its granted authority; people decide which teachings to
accept. Git versions the source records, while configured CI and runtime hooks
validate changes and check review coverage.

<!-- toc:start -->
**Table of contents**

- [Install](#install)
- [Responsibilities](#responsibilities)
- [Guides](#guides)
- [Hierarchy terminology](#hierarchy-terminology)
<!-- toc:end -->

## Install

Requires Python 3.12+ on macOS or Linux, excluding Python 3.14.1.

```bash
pip install witful
witful --help
```

Use `witful init ./my-collection` to create an empty collection when you need a new
one. Keep existing collections in place and pass `--repo` to the relevant commands.
See [CLI contracts and first run](https://github.com/astrivant/identity/blob/main/docs/CLI.md).

Optional extras are `postgres` for PostgreSQL and `sapience` for MCP transport.
The Sapience adapter is under development in this checkout until the next release;
use `pip install '.[sapience]'` here to try it. The core package does not install
Sapience or its vector database.

## Responsibilities

The workflow is to retrieve applicable guidance, perform authorized work, record
what happened, and review the result against that guidance. Witful supports the
record and review steps through these capabilities:

- Validate the attrs/cattrs hierarchy and append-only journals.
- Index lessons in SQLite or optional PostgreSQL.
- Preserve concise decisions and source snapshots for reproducible replay.
- Record observed applications, tool use, and project checkpoints.
- Track explicit runtime provenance, reconcile pending tasks, and compare native evidence across instances.
- Render plots from recorded evidence and explicitly export selected awareness figures.
- Check publication inputs with the PII scanner and configurable deny terms.
- Install and synchronize encrypted, signed private collections.
- Isolate concurrent sleeves, sign backups, and reconcile their histories before closure.
- Optionally project reviewed concepts into Sapience and save generated review proposals.

Source journals remain owned by the collection. Generated proposals require review
before they become accepted lessons. Application counts describe recorded use;
completion checks establish review coverage. Evidence quality, permission checks,
and runtime enforcement remain responsibilities of the people and integrations
using those outputs.

## Guides

- [Completion audits](completion.md): review every concept before handing work back.

[Architecture and collection conventions](https://github.com/astrivant/identity#readme),
[CLI](https://github.com/astrivant/identity/blob/main/docs/CLI.md),
[Sapience integration](https://github.com/astrivant/identity/blob/main/docs/sapience.md),
[awareness figures](https://github.com/astrivant/identity/blob/main/docs/awareness.md),
[private collection setup](https://github.com/astrivant/identity/blob/main/docs/private-collections.md),
[multisleeving](https://github.com/astrivant/identity/blob/main/docs/multisleeving.md),
[observed instances](https://github.com/astrivant/identity/blob/main/docs/instances.md),
[security](https://github.com/astrivant/identity/blob/main/SECURITY.md), and
[development](https://github.com/astrivant/identity/blob/main/CONTRIBUTING.md).


## Hierarchy terminology

The hierarchy is `Identity -> Discipline -> Skill -> Lesson -> Insight`. An Insight
is a concrete, reusable takeaway from a sourced Lesson. The Python type is
`Insight`, and lessons and catalog annotations expose an `insights` tuple.

New catalogs use version 2 and the `insights` field. Version-1 catalogs with
`lemmas` remain readable and serialize with their original spelling, preserving
content-addressed snapshots and decision chains. To migrate a current catalog,
change its version to 2 and rename each annotation's `lemmas` key to `insights`
together. Keep concept IDs unchanged. Do not edit historical journals or snapshots.

Checkpoint comparisons retain their existing digest representation, so the rename
alone does not count as learning. Current plots, CLI output, and MCP projections
use Insight; existing projected memory IDs remain stable. Historical replay still
requires acknowledgment of renderer changes before producing different plot bytes.
