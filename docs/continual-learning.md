# Continual learning

Continual learning revisits recorded choices using what the collection knows now.
It preserves the original task, constraints, choice, and knowledge snapshot, then
adds a separate reviewed assessment. It does not rewrite history or treat a lucky
outcome as proof that a decision was sound.

## Review cadence

`knowledge/reflection.json` is optional. Defaults apply to new and existing
collections:

```json
{
  "enabled": true,
  "interval_commits": 100,
  "batch_size": 20
}
```

Cadence counts all commits on the selected checkout's first-parent history,
including generated commits. The first review becomes due at 100 commits. After a
completed round, it becomes due after another 100 commits. Building a plan or a
figure never acknowledges a review. A due review remains due until recorded.
No recorded decisions means no review is due. Manual earlier reviews are allowed.

Batches prioritize decisions never reviewed, then the least recently reviewed;
ties prefer newer decision events. Historical revisions are included independently.
This rotates through larger histories without repeatedly choosing only recent wins.
The plan also identifies earlier choices for each subject. A shared subject does
not prove identical context: read the actual task, rationale, and original snapshot.

Use complete Git history. Shallow clones and a missing or divergent previous review
anchor fail visibly instead of inventing a commit count. CI uses `fetch-depth: 0`.
Encrypted installations pass their transport checkout as `--history-repo`; their
local source collection need not itself be a Git checkout.

## Review a batch

```bash
witful reflection --repo COLLECTION plan --history-repo CHECKOUT
witful reflection schema
witful reflection --repo COLLECTION record --history-repo CHECKOUT --input assessments.json
witful reflection --repo COLLECTION build
```

The plan defaults to `COLLECTION/.cache/reflection-plan.json`; `--output` overrides
it. Read the immutable Life events and referenced original snapshots alongside
current lessons. Provide a JSON array containing one assessment per requested
`decision_id`, sorted by that identifier. The generated schema defines the fields.

For each assessment:

- `current_choice` and `rationale` describe what you would choose now under the
  **original** task and constraints. Cite current concepts in `knowledge_ids`.
- `current_support` rates present support for the **original choice**, not confidence
  that an alternative would succeed. It requires current knowledge references.
- `observed_outcome` records what happened, supported by `outcome_evidence`.
- `context_change`, `context_effect`, and `context_evidence` separately describe
  circumstances after the decision. Association does not establish causation.
- `proposed_lessons` remain pending proposals. Promote them through the normal
  sourced lesson workflow only after review; no journal is silently rewritten.
- `seek_help` flags a useful opportunity to consult a colleague or another agent.
  Recording the flag does not launch agents or send messages.

All scores use an ordinal rubric: **-2 strongly negative, -1 negative, 0 neutral,
1 positive, 2 strongly positive**. Use `null` when evidence is missing. Unexecuted
alternative outcomes remain hypothetical and cannot fill `observed_outcome`.
A complete batch can contain unknown outcomes; absence is not failure or neutrality.

Each append retains the exact current knowledge snapshot, Git cadence revision,
observation time, and a hash link to the previous review. The knowledge snapshot
includes working-tree changes; the commit is a cadence anchor, not a claim that
all current files were committed. Identical retries at the same knowledge state
and revision reuse the existing record. Corrections append a new complete round.

## Read the figures

**Past decisions, current knowledge** plots present support for the old choice on
X and its observed outcome on Y. A well-supported decision with a poor outcome
warrants investigation of constraints and uncertainty. A poorly supported decision
with a good outcome warrants checking whether its success transfers to other cases.

**What changed afterward** plots observed outcome on X and subsequent change in
circumstances on Y. It helps identify outcomes worth revisiting as context evolves.
Neither axis claims that the decision alone caused the observed change.

Points aggregate identical ordinal ratings and display their decision count.
Unknown pairs are excluded and counted explicitly. There is no jitter, fitted
trend, composite proficiency score, or fabricated historical rating. Distances on
this ordinal grid should not be interpreted as calibrated effect sizes. Both
plots use the latest review per decision; the journal retains every earlier round.
`reflections.json` exports those rounds for detailed inspection on protected storage.

## Default automation and privacy

Managed private collection CI generates both plots and a review plan on each
refresh. The due flag and batch count are visible in logs; private decision text
stays in `reflection-plan.json` inside the signed, encrypted figure archive.
Restore that archive or generate a local plan to conduct the review. CI does not
call model providers, assign scores, or accept proposed lessons.

Only collections explicitly allowing readable figures show their review plots in
GitHub. Setting `enabled` to false stops generation and removes previously
published reflection figures on the next managed refresh. Existing Git history is
unaffected. There is no automatic projection of these figures into a public resume.

The upstream README uses labeled synthetic examples, regenerated in the same CI
pipeline and published after successful main tests. No maintainer's personal
records are read. The agent skill checks cadence and surfaces useful findings for
discussion; it does not claim background activity between sessions.
