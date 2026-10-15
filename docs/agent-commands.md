# Agent chat commands

These are portable instructions to an agent that has loaded this project's
[SKILL.md](../SKILL.md). They are not native host controls. [Delivery helpers](delivery.md) provide
explicit executable steps behind the PR and upload workflows.
Only deliberate user invocations act; quoting or documenting a command does not.
The [CLI reference](CLI.md) describes executable commands.

## Durable definitions

Keep reusable command behavior in this public project by default through the normal
reviewed contribution workflow. Keep the canonical catalog in this guide and link
it from the README. Update this contract, the root agent entrypoint and collection
template together when behavior changes. An owning collection records
its sourced teaching and any personal aliases/bindings separately. Never publish
private records, profile names, local paths or teaching provenance as generic
examples. A proposed upstream definition is not a released downstream capability.

Document each canonical command with aliases nested beneath it. Preserve established
meanings when adding a new definition; resolve an actual conflict with its owner.
Reading this guide grants no side effects. Invocation supplies task scope; existing
checks, review gates, signing and credential boundaries still apply.

## Command catalog

- **`Push`**: publish the selected worktrees through their normal checks, signed commits and configured remotes; verify each accepted remote revision.
  - Alias: `push` (case variant).
- **`Tag`**: reconcile the selected project's authorized work and publish a new signed compatible release tag under its release contract.
  - Alias: `tag` (case variant).
- **`Tag All`**: apply that release workflow to explicitly selected active projects, using a configured work ledger when available.
  - Alias: `tag all` (case variant).
- **`search soul`**: review the selected repository against the active collection's complete applicable awareness tree, report evidence and gaps, and preserve source provenance. It is a review, not implicit repair or release authorization.
  - Alias: `soul search`.
- **`project pr rebase`**: refresh and rebase the selected project's open PR branches onto their intended bases, validate and publish the results, and return the review order described below.
  - Aliases: none currently defined.
- **`project pr show`**: return a read-only ordered list of open PR links, sizes, dependencies, blockers and current CI.
  - Aliases: none currently defined.
- **`identity deactivate`**: suspend the active collection's optional guidance and automatic learning for this conversation when the agent supports this convention.
  - Aliases: none currently defined.
- **`identity activate <name>`**: load an explicitly identified existing collection and its current guidance. Keep concrete profile names in that collection; a failed lookup preserves the previous selection.
  - Aliases: none currently defined.
- **`Lesson: <teaching>`**: record an accepted, sourced transferable teaching in its owning collection with a canonical Skill and Discipline.
  - Alias: `New Lesson: <teaching>`.
- **`Insight: <finding>`**: record a supported finding under a sourced Lesson, with evidence, remedy or pending action, and uncertainty. Selected response text can supply the finding's context.
  - Aliases: `Insight. Record this`, `New insight: <finding>`.
- **`Insight -> Lesson`**: promote a selected finding into reusable guidance while preserving its original Insight and provenance.
  - Aliases: none currently defined.
- **`New command: <definition>`**: persist the canonical meaning, aliases and scope in the owning collection and propose its reusable generic contract upstream.
  - Aliases: none currently defined.

Identity selection changes optional guidance only. It does not erase conversation
context, switch credentials, reset tools or establish a privacy boundary. An
inactive collection receives no automatic observations; explicit maintenance of
that collection remains a separate authorized task. Private collection publication
follows its existing encryption and review policy.

## PR and MR inventory and review order

Select the current or explicitly named existing repository. Use its established
GitHub/GitLab SDK to read open PRs and MRs, their exact heads, bases, descriptions,
comments and review state. Preserve explicit exclusions and holds. The executable
helper accepts repeated `--remote` selectors for combined inventories and `pr`/`mr`
aliases. It binds each mutation to one provider destination. See [delivery](delivery.md).

Order prerequisites before dependents. Among independent eligible PRs, sort by
added plus deleted lines, then changed-file count and PR number. Include the metric
and note generated/binary payloads separately when relevant; changed lines are not
transfer bytes. Identify dependency cycles or uncertain relationships as blockers,
not an invented order. Return numbered clickable links with a short purpose and
exact-head CI status. Refresh this inventory after changes.

## Rebase and publication

Save the observed remote heads and local recovery refs before rewriting. Use clean
isolated worktrees so existing staged and unstaged work remains intact. Rebase
prerequisites first. When a parent branch moves, replay only the dependent PR's
commits using its old and new base, preserving the stack. Already-current branches
need no synthetic commit. Inspect conflicts and range-diffs for both intended
behaviors, and explain unresolved semantic decisions.

The explicit rebase command authorizes necessary rewrites of the selected feature
branches. It does not authorize rewriting main/tags, merging, releasing, closing
PRs, or silently changing their target branches. Re-sign rewritten commits with
the intended identity, run focused tests and all configured hooks, then use an
exact-head lease: `git push --force-with-lease=refs/heads/BRANCH:OLD_SHA REMOTE
HEAD:refs/heads/BRANCH`. If the remote changed, stop that push and reassess; never
replace the lease with an unconditional force push. See the
[Git push contract](https://git-scm.com/docs/git-push).

Verify the remote ref and host signature status, follow the current-head CI, and
update each PR body with intent, old/new revisions, validation and the next review
action. Distinguish local checks, hosted success and pending review. Continue
independent PRs if one is blocked, and leave the original recovery heads available.

## Small-first upload recovery

For independently uploadable files, send smaller byte sizes first, useful metadata
before large payloads, and verify each remote batch. Retry the largest files
separately while tracking incomplete delivery and preserving coherent dependencies.

A Git push sends reachable objects in a [pack](https://git-scm.com/docs/pack-protocol),
so adding paths in size order cannot guarantee wire order or a partial accepted
branch. Where authorized, publish coherent signed metadata/source commits to a
non-deploying recovery branch and verify each accepted ref before appending larger
payloads in later commits. A large object reachable from an earlier commit still
needs transfer. Do not rewrite published history or introduce LFS/storage changes
implicitly. Use an established artifact-upload contract when one exists, preserve
privacy, and never claim a failed push retained files without remote evidence.
