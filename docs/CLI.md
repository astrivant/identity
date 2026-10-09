# CLI

All commands accept `--help`. Commands act on an explicitly selected local
collection and never infer a need to publish it.

```bash
witful init ./my-knowledge
witful lessons --repo ./my-knowledge add --topic Testing --lesson 'Use explicit inputs.' --source 'Team review'
witful lessons --repo ./my-knowledge search explicit
witful --repo ./my-knowledge build
```

Unassigned topics remain visible as Unclassified. Edit `knowledge/catalog.json`
to group exact topic names under disciplines and skills. Generated JSON Schemas
live under `knowledge/schemas/`; `witful --repo PATH check` validates the
sources and schema drift.

| Command | Purpose |
| --- | --- |
| `init PATH` | Create an empty collection; never overwrite an existing directory |
| `lessons [--repo PATH] add/search/check/sync/status` | Source journal and SQLite/PostgreSQL search |
| `[--repo PATH] show [ID]` | Inspect the hierarchy and observed counts |
| `[--repo PATH] record --task ID --discipline ID --concept ID --outcome verified --evidence TEXT` | Append an actual application; repeat `--concept` for co-use |
| `[--repo PATH] build` | Generate schemas, usage charts, hierarchy, and weighted graph |
| `life [--repo PATH] record --input decision.json` | Append a sourced decision with a replay snapshot |
| `life [--repo PATH] show --key KEY --history` | Inspect prior choices and explicit supersession |
| `life [--repo PATH] replay --output-dir PATH` | Reconstruct saved inputs; toolchain drift fails unless explicitly acknowledged |
| `life [--repo PATH] seed` | Transactionally seed an explicitly configured PostgreSQL archive |
| `repertoire [--repo PATH] check/build/record --input use.json` | Validate the toolbox/problem taxonomy, record actual use, and plot task frequency |
| `checkpoints [--repo PATH] record --project PATH --project-id ALIAS` | Record a Git boundary and update its local checkpoint mirror |
| `checkpoints check/diff/build/schemas/sync` | Validate, compare, render, or explicitly mirror checkpoint history |
| `privacy scan [--repo PATH] [--staged] [--terms-file PATH]` | Scan publishable source; redacted findings, exit 1 for matches, 2 for incomplete scans |
| `registry NAME... [--stdin] [--refresh] [--offline]` | Batched PyPI observations, cached for six hours; exit 2 for unknown results |

Life decisions contain `key`, `title`, `task`, `choice`, `rationale`, `source`,
and `concept_ids`; revisions must name the current event as `supersedes`.
The schemas are the authoritative field definitions. Recorded rationale is a
concise engineering explanation, not hidden model reasoning. Application and
decision journals are separate evidence; lookups are not applications.

Registry results are `registered`, `not-registered`, or `unknown`. A 404 is not
proof that PyPI will accept registration. `--ttl-seconds`, `--cache-dir`, and
`--timeout-seconds` control caching and request bounds. A 429 cooldown applies
across the batch and later invocations, even with `--refresh`.

## Toolbox and problems

`knowledge/repertoire.json` owns `tools` (id, name, kind, purpose, reference)
and `problems` (id, name, optional parent). Parents form an acyclic hierarchy
from broad concepts to concrete problem types. Empty collections are valid.
`knowledge/tool-uses.jsonl` contains explicit observations, never a dependency
scan interpreted as historical use. `repertoire build` emits schemas, an exact
input export, a frequency histogram, and the problem graph under `docs/assets/`.

To record a use, provide a JSON object with `id` and `observed_at` as empty
strings (assigned by the command), a stable `task`, sorted unique `tools`,
`problems`, and `concepts` IDs, and concise actual `evidence`. Referenced IDs
must exist; concepts belong to the main knowledge hierarchy. Repeating the same
observation is a no-op. Later observations of the same task replace its current
counts while retaining previous evidence. Ancestor counts deduplicate each task.
These repertoire plots have their own exported inputs; Life replay covers its
saved lesson/knowledge inputs and does not implicitly archive this separate catalog.

See [project checkpoints](checkpoints.md) for visit ordering, evidence semantics,
database mirroring, and main-branch rendering.
