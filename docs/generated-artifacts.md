# Generated artifacts and conflict repair

The [inventory](../.github/generated-artifacts.json) declares generated outputs,
canonical inputs and whether trusted CI can repair a conflict. Validation runs in
pre-commit and source CI. New generators must add their outputs and explain their
repair boundary; declaring an output does not grant permission to execute its generator.

## Automatic repair

Prevent generated conflicts before adding repair privileges. Native diagram evidence
uses [independent path records](native/diagrams/README.md#source-and-configuration-binding),
so each PR changes only the evidence it affects. The combined inventory is checked
against actual source and output hashes after merging. A shared format declaration
has no changing revision or date. No custom Git merge driver or CI write permission
is needed; genuine competing changes remain visible for review.

[Provider observations](provider-contracts.md#versioned-inputs-and-results) stay in
run artifacts when selected contracts have not changed. Only changes to the consumed
contracts produce baseline update proposals. This avoids unrelated source commits
and freshness timestamps becoming shared conflict points.

The existing [CI pipeline](../.github/workflows/ci.yml) calls a separate
[repair stage](../.github/workflows/stage-repair.yml) on PR target activity,
default-branch pushes and a six-hour schedule. It becomes active only after the
workflow reaches the trusted default branch. Every scan considers all open target
branches in dependency order, with parent PRs before their children. Retargeting or
closing a parent also triggers a scan. GitHub calculates mergeability asynchronously;
unknown results wait for the next scan.

The stage reads trusted default-branch code and inert Git objects. It never checks
out, imports, installs or runs PR source. Same-repository, open, non-draft PRs
against any branch are eligible, including chains of PRs. Each declared target
branch supplies the actual merge base; it does not supply privileged tooling.
GitHub runs
[`pull_request_target` from the default branch](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target),
independently of the PR target. Both candidate branches must retain that trusted
revision's inventory. Matching policy edits in two stack branches cannot authorize
repair. Forks and changed inventories are excluded.
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

The publisher refreshes each PR after its prerequisites, rechecks exact head/base
branch names and commit bindings, and creates a GitHub-signed commit
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

To format ownership, run `python -m ownerloom --write`, review and stage the
result, then run pre-commit. The pre-push check reads committed HEAD. Neither hook
stages files, creates commits or grants new directory ownership.
