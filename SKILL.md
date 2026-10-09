---
name: witful
description: Curate a user-owned knowledge collection with typed lessons, observed applications, decision replay, and privacy checks. Use for creating or maintaining a Witful collection, searching sourced lessons, recording actual applications, inspecting publication inputs, or explicitly publishing selected awareness figures.
---

# Identity with Witful

Read [CLI contracts](docs/CLI.md) and [SECURITY.md](SECURITY.md). Locate the user's
existing collection before making changes; create one only when requested.
Current instructions take precedence over stored lessons. Ask which rule wins
when genuinely conflicting standing rules cannot be scoped independently.

Search relevant lessons before work. Append source-supported observations and
explicit supersessions; never invent historical applications or infer mastery
from counts. Record actual use with task, concepts, outcome, and evidence.
Life records concise decisions, not hidden reasoning. Preserve replay snapshots;
acknowledge renderer drift instead of rewriting historical fingerprints.

Use `repertoire` to maintain tool references and classify actual problems from
concrete to abstract. Record verified tool use with task evidence; never infer
frequency from installed packages. Keep source observations current; main CI regenerates plots. Review plot
subtitles and layout when changing their renderer.

Use small reusable scripts for repeated tasks when expected reuse justifies the
cost. `witful registry` checks names in batches; keep unknown responses and
cached observations distinct from registration eligibility.

Record checkpoints after meaningful project work and before moving to another
project, using a stable project alias and its committed HEAD. Read
[the checkpoint contract](docs/checkpoints.md). The first snapshot is a baseline;
never reconstruct undocumented past use or infer learning from a repository switch.
Commit the reviewed checkpoint journal; let the collection main workflow render
its plots and synchronize its SQLite mirror. Remote database writes remain explicit.

## Publish awareness figures

For a requested figure export or resume rebuild, read [awareness publication](docs/awareness.md)
and preserve the user's selection in `knowledge/awareness.json`. Check the installed
CLI's `awareness --help`; configuration, output paths, and schemas are described in
[CLI contracts](docs/CLI.md#awareness-publication).

Use `witful awareness --repo COLLECTION build` to regenerate a local bundle from
current evidence. Inspect selected plot labels before sharing: PNGs can expose
project names and relationships even though the bundle omits source journals.
Awareness generation omits outer titles and subtitles so the receiving document
owns its headings; retain axis labels and legends. Check the [working-emphasis map](docs/knowledge-map.md)
for the distinction between a bounded current view and the full retained hierarchy.
An empty selection publishes nothing. The receiver separately controls its allowed
GitHub actors and enabled appendix figures; preserve all disabled defaults.

Run `witful awareness --repo COLLECTION push` only when the task authorizes
publication to the configured repository. Use the existing authenticated GitHub
CLI; do not create tokens or change repository permissions implicitly. Report
an accepted dispatch separately from a completed workflow and verified PDF.
For an uncertain result, inspect the destination's Actions run before retrying;
identical data reuses its commit, but another dispatch can start another build.
Stop when authorization or validation fails and report the specific blocker.

Validate sources and run relevant tests. Render and inspect affected plots locally
when developing their renderer; routine evidence updates rely on CI generation. Every study plot should answer a concise question stated
in its subtitle. Inspect publication inputs with `witful privacy scan`, using
private deny terms where relevant. A passing scan is not proof of anonymization.
Do not publish records, upload archives, seed remote databases, or generate keys
without the user's task authorizing that action.


## Private copies and installed collections

Read [private collection operations](docs/private-collections.md) for requested
setup, migration, or synchronization. Public forks cannot become private; use the
explicit private-copy installer, preserving the user's existing Codex settings and
collection. Run setup only when requested; it creates keys and updates repository
secrets. Reuse the saved key directory after partial setup, never silently rotate.

The installed collection is local plaintext. Seal only the documented source
allowlist, then commit the named encrypted files when publication is authorized.
Never add the Codex home or key directory wholesale. Main CI replaces the library
README with the user's dashboard and renders current figures. Full figures remain
encrypted unless the user explicitly enables readable figures; explain that their
labels then remain in Git history. Keep hosted refresh verification distinct from
local signature, encryption, or schema checks.

## Optional Sapience integration

Read [Sapience operations](docs/sapience.md) before using `witful sapience`.
Export first for inspection; synchronize only when the task authorizes sending the
selected collection to the configured server and embedding provider. Keep collection
ID and namespace stable across retries. Inspect interrupted operations through
readback; do not fall back to random-ID `save_memory` calls.

Generated briefs are pending proposals. Review their claims and source memories,
then use ordinary lesson commands for an explicitly accepted teaching. Never rewrite
journals with generated summaries. Awareness figures serve an optional professional
signature and personal reflection; preserve disabled defaults and record evidence
rather than inventing measures of capability.

For a shared MCP deployment, use the Sapience guide's authenticated `--url` transport
and bearer-token environment variable. Keep PostgreSQL memory and ledger ownership
in the Sapience service; do not share local SQLite/Chroma files between replicas.
Identity owns its journal-worker chart under `helm/witful/` and generated service
configuration under `services/`. Regenerate Compose from the chart/profile and
validate moved paths in CI and pre-commit when changing this layout.
