# Completion audits

A completion audit reviews every Identity, Discipline, Skill, Lesson, and Insight
before work is handed back. It preserves the hierarchy and teaching provenance,
requires explicit applicability decisions, and rejects missing or stale coverage.
The implementation uses the existing compiler and generated JSON Schema; it does
not introduce a second knowledge model or infer completion from usage counts.

## Review a task

Use a collection containing `lessons.jsonl` and `knowledge/catalog.json`. Keep
`.witful/` ignored by Git. Select the installed environment explicitly when running
from another project's directory. The collection must have a committed Git HEAD.

```bash
witful completion --repo /path/to/collection plan \
    --task project:change-reference \
    --workspace /path/to/project \
    --output /path/to/collection/.witful/completion/review.json
```

Run this after the final changes and checks. Review the generated JSON entries
individually. Shared evidence may support several entries, but a parent checkbox
does not review any child. Keep the generated IDs, labels, statements, and sources.
The script never executes commands found in teachings or evidence references.

| Status | Required review |
| --- | --- |
| `pending` | Unreviewed; always fails the check. |
| `satisfied` | State what was done and provide nonempty evidence references. |
| `not_applicable` | Explain why this requirement does not apply to this task. |
| `blocked` | State the blocker and concrete next action; allowed only with an incomplete handoff. |
| `historical` | Generated for explicitly superseded Lessons and their Insights; preserve unchanged. |

An applicable child beneath an excluded parent is a contradiction and fails.
Supersession preserves the original nodes and exempts only the superseded teaching
and its descendants. Unknown topics remain visible through the compiler's existing
Unclassified group. Relationships contribute to the source digest without creating
additional owners or recursive traversal cycles.

```bash
witful completion --repo /path/to/collection check \
    --task project:change-reference \
    --workspace /path/to/project \
    --input /path/to/collection/.witful/completion/review.json
```

Exit zero means review coverage passed. Output also includes `complete`: it is
false when `outcome` is `handoff`. To hand back unfinished work, set that outcome,
provide `handoff_reason`, and mark unresolved applicable entries `blocked` with a
next action. Pending entries still fail. Exit one means coverage gaps or stale
bindings; exit two means invalid input or a failed local operation.

Repeat `--workspace` for every selected project. The collection is always included.
A new task, changed hierarchy or relationship, new commit, index change, or changed
tracked/nonignored file invalidates the previous snapshot. Regenerate using
`plan --replace` and review again; replacement deliberately clears attestations.
`witful completion --repo /path/to/collection schema` emits the closed source schema.

## Run before a Codex handoff

The adapter supports the official synchronous `UserPromptSubmit` and `Stop`
[hook contract](https://learn.chatgpt.com/docs/hooks). Generate a reviewable definition:

```bash
/path/to/collection/.venv/bin/python -m witful.completion \
    --repo /path/to/collection hook-config --identity example
```

Merge the emitted definition into the desired user or project `hooks.json`,
preserving existing hooks and backing up an existing configuration first. The
command uses the selected Python interpreter's absolute path. Review and trust
the exact hook definition through Codex's native hook controls. Generating JSON
neither installs nor trusts a hook. A definition changed after trust needs review
again. Keep the hook synchronous: an asynchronous notification cannot gate Stop.

Each prompt supplies the command for its own review. Stop checks that review
against the current tree and workspace. Missing, malformed, or stale reviews block
handoff with a bounded diagnostic. Hook continuation does not bypass the audit;
finish the review or record an explicit incomplete handoff. The adapter does not
register a runtime instance or claim to replace the separate instance/sleeve guards.

Session IDs are hashed into separate local directories; prompt bodies, final
assistant messages, transcripts, and credentials are never persisted or read from
transcript files. Exact `identity deactivate` user prompts suspend that conversation's
audit. Exact `identity activate example` prompts restore it only after the configured
collection can be read. Quoted commands and unknown identity names do not switch
modes. Minimal session routing state remains local; other conversations and
collections retain their state. Configure only the intended collection for a given
identity. Do not install a second collection's hook into another identity's runtime.

The adapter snapshots its collection and the hook's Git workspace. For a non-Git
working directory, it snapshots the collection and requires explicit evidence for
other outputs. Multi-project manual checks can select additional workspaces with
`--workspace`. Native hooks do not infer all repositories mentioned in conversation.

## Evidence and storage boundaries

Coverage is mechanically checked; evidence references are caller attestations.
The script does not certify their truth, prove bug-free code, inspect remote CI,
or determine whether the task's requirements were understood correctly. Review
quality still depends on the recorder and supporting checks.

Workspace fingerprints cover HEAD, the index, tracked files, and nonignored new
files. Symlinks are hashed as links without following targets. Files over 32 MiB,
submodule directories, and unsupported file types fail visibly. Ignored outputs,
external services, non-Git artifacts, and runtime behavior require separate evidence.
Git metadata is checked again after capture; the working tree is not locked against
concurrent editors. Perform the review after writers and checks have finished.

Runtime JSON lives under the collection's ignored `.witful/completion/` directory
with private directory permissions. It contains teaching text, evidence, workspace
paths, and digests, so it stays in the owning private collection. It is retained
until the owner removes it; no automatic upload, database projection, or telemetry
is performed. Remove a completed session directory only after its audit record is
no longer needed. Avoid putting secret values or raw conversations in evidence.
Use the collection's reviewed audit/checkpoint workflow for durable redacted events.
