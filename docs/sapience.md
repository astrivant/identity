# Sapience integration

Witful can project reviewed concepts into [Astrivant's Sapience fork](https://github.com/astrivant/sapience).
Sapience supplies MCP retrieval and generated context briefs. Identity retains
ownership of source journals, classification, explicit decisions, and evidence.
This integration is optional and independent of awareness figure publication.

## Install and inspect

The adapter is available from this checkout until the next Witful release:

```bash
pip install '.[sapience]'
witful sapience --help
witful sapience --repo ./collection export --collection-id my-collection --namespace reviewed
```

`export` requires no server or model credentials. Inspect
`.witful/sapience-projection.json` before external processing. It contains concept
text, source references, timestamps, and relationships and may be sensitive.
Use a stable, nonsecret collection ID and a concrete namespace; neither should be
a personal home path. Keep both unchanged when moving the collection or retrying.

Install the fork in a separate Python environment at the tested commit:

```bash
python3 -m venv .venv-sapience
.venv-sapience/bin/python -m pip install 'sapience-mcp @ git+https://github.com/astrivant/sapience.git@812ec0545486a5c1e3a1d2b10a846a9694f5d3e2'
```

See its [integration guide](https://github.com/astrivant/sapience/blob/812ec0545486a5c1e3a1d2b10a846a9694f5d3e2/docs/witful.md).
The upstream PyPI release does not yet provide the required structured upsert contract.
Select the resulting `sapience` executable explicitly; no shell interprets it.

```bash
export SAPIENCE_DATA_DIR="$PWD/.witful/sapience"
export EMBEDDINGS_PROVIDER=local
witful sapience --repo ./collection sync --collection-id my-collection --namespace reviewed --server /path/to/sapience
```

Sapience defaults to OpenAI embeddings. `local` avoids sending concept text to
that provider, but may download the embedding model on first use. Keep provider
choice consistent with an existing database; changing vector dimensions requires
a separate database and a fresh projection. External embeddings use `OPENAI_API_KEY`.

## Ownership and synchronization

The projection includes Identity, Discipline, Skill, Lesson, and Lemma nodes.
Ancestors are flattened rather than duplicating descendant journals. IDs are
SHA256-derived from collection ID, namespace, and source concept ID. Each record
retains schema version, source ID, kind, source reference, source revision, content
hash, observed time when recorded, supersession, containment, and sourced graph edges.
Superseded lessons and their lemmas are marked historical. A revision fingerprints
the source representation, not a fabricated version number or commit.

Synchronization discovers structured tool contracts, calls `upsert_memory`, then
checks every field through `read_memory`. Text and structured JSON must agree;
malformed results and error envelopes fail the operation. Rerun the same command
after a partial failure: accepted IDs are reused, unchanged records are not embedded
again, and creation/access history survives replacement. Changed content is embedded
before the existing record is replaced. A namespace collision is rejected.

Updates are atomic per memory, not transactional across a whole collection. The
adapter does not delete remote memories removed from a local catalog. Use a new
namespace for a complete replacement snapshot, or explicitly manage obsolete records
in Sapience. Namespaces are logical partitions, not authentication boundaries.
Applications, Life snapshots, and raw agent transcripts are not synchronized by this
initial adapter; figures continue to use Witful's validated local evidence.

## Generated proposals

```bash
witful sapience --repo ./collection propose --namespace reviewed --topic "release review" --server /path/to/sapience
```

`propose` invokes Sapience's `get_context_brief`. For nonempty retrieval this sends
memories to Anthropic using `ANTHROPIC_API_KEY`; local embeddings do not make synthesis
local. The response is validated and saved under `.witful/proposals/` with
`pending-review` status, source memory IDs, receipt time, and a content hash.
A proposal records which memories were retrieved; it does not verify the model's claims.

Review the proposal against the source records. If you accept a teaching, use the
ordinary `witful lessons --repo COLLECTION add` workflow with explicit attribution.
No generated response rewrites the source journal or becomes an accepted lesson
without that separate review step.

## Runtime boundary

The adapter forwards `SAPIENCE_DATA_DIR`, `MEMORY_DB_PATH`, `LEDGER_DB_PATH`,
`SAPIENCE_NAMESPACE`, `EMBEDDINGS_PROVIDER`, `EMBEDDINGS_MODEL`, `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, and `PYTHONPATH`, when set, plus the MCP SDK's minimal process
environment. Trust the chosen executable and Python import path. Requests have a
120-second response timeout. Errors omit raw server/provider payloads.

Sapience's local database and these review artifacts are plaintext. Encrypted Git
transport for a private Identity collection does not encrypt the MCP server's storage.
See [SECURITY.md](../SECURITY.md) before synchronization.
