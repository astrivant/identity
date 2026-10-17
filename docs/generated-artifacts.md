# Generated artifacts and conflict repair

The [inventory](../.github/generated-artifacts.json) declares generated outputs,
canonical inputs and whether trusted CI can repair a conflict. Validation runs in
pre-commit and source CI. New generators must add their outputs and explain their
repair boundary; declaring an output does not grant permission to execute its generator.

## Automatic repair

The existing [CI pipeline](../.github/workflows/ci.yml) calls a separate
[repair stage](../.github/workflows/stage-repair.yml) on PR target activity,
default-branch pushes and a six-hour schedule. It becomes active only after the
workflow reaches the trusted default branch. GitHub calculates mergeability
asynchronously; unknown results wait for the next scan.

The stage reads trusted default-branch code and inert Git objects. It never checks
out, imports, installs or runs PR source. Same-repository, open, non-draft PRs
against the default branch are eligible. Forks and changed inventories are excluded.
The planner builds an isolated merge tree and stops if any conflict lacks a supported
repair. It preserves clean changes from both parents and refuses ambiguous inputs,
mode changes, symlinks, submodules and oversized proposals.

CODEOWNERS repair supports literal rules with one unchanged owner group and
unchanged leading commentary. Independent additions/removals are merged by key and
sorted; existing broader scopes remove redundant children without adding ownership.
Wildcards, section comments and changed owners require review. The normal ownership
compiler preserves these as ordering boundaries; local compilation is not permission
to resolve their meaning automatically.

A `copy` inventory entry can copy one cleanly merged canonical blob to one exact
output. No arbitrary renderer command is accepted. Identity currently has no such
copy outputs. Provider contracts, chart schemas, mixed authored/generated Markdown,
Compose and figures remain `manual`: regenerate them with normal project tooling
after their source conflicts are resolved. In particular, run the
[provider refresh](provider-contracts.md#refresh-the-contracts) instead of selecting
a timestamp or specification pin from one side of a conflict.

## Publication and review

The publisher rechecks exact head/base bindings, creates a GitHub-signed commit
with both parents, verifies its signature, then advances only the PR branch without
force. It cannot merge a PR or update the default branch. Concurrent changes stop
publication. The Actions summary records the PR, repaired paths and new revision.
Ordinary PR CI and review remain required; approve a GitHub-token-triggered run if
GitHub places it behind an approval gate. A repair commit is not a passing build.

Run the same inventory and planner checks locally:

```bash
python scripts/ci/repair/plan.py --check
pytest -n 0 tests/ci/test_generated_repair.py tests/ci/test_generated_repair_workflow.py
node --test scripts/ci/repair/repair.test.mjs
```

Real temporary Git repositories cover deterministic merges and refusal boundaries.
Synthetic SDK responses cover signature refusal, current-ref checks and non-force
publication; they do not establish live bot signing or branch-protection behavior.

To format ownership, run `python -m scripts.ownership --write`, review and stage the
result, then run pre-commit. The pre-push check reads committed HEAD. Neither hook
stages files, creates commits or grants new directory ownership.
