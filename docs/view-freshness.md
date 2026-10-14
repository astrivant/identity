# Synthetic evidence view freshness

Every push to main and every pull request rebuilds the committed project-chapter
examples from `examples/project-chapters/knowledge/checkpoints.jsonl` using locked
tools. These are synthetic project names and revisions, not personal observations.
The render job is independent of source tests and uploads all SVG, PNG, JSON and
provenance files as `synthetic-evidence-views` for seven days.

Run `bash scripts/ci/render-views.sh` in the locked project environment to reproduce
it. The source/output hashes and immutable source revision appear in
`docs/assets/project-chapters/view-provenance.json`. Missing inputs, missing outputs,
or stale hashes fail. Unchanged plot bytes can be correct; compare the receipt and
source inputs instead of image timestamps. Each source revision has its own CI
concurrency group, so a newer pending push does not cancel an older render.

Main requires review. CI does not bypass that requirement or write example files
to main. Download the matching run's artifact with `gh run download RUN_ID --name
synthetic-evidence-views --dir docs/assets/project-chapters`, inspect the images and
receipt, and include approved SVG/JSON output changes in a normal PR. PNG previews remain
CI artifacts because the public source privacy gate cannot inspect binary images. The downloaded receipt
identifies the source revision; do not present unmerged output as the current README.
No automatic generated-file PR or change to branch protection is configured.

The generic `scripts/ci/publish-views.sh` helper is available to private collection
consumers that explicitly permit generated main commits. It rejects public
repositories, verifies source/output digests, fences stale writers, and publishes
only the allowlisted views through GitHub's signed commit API. Collections must
populate and publish their own reviewed evidence during work. A backup archive does
not feed a renderer without an explicit authenticated ingestion path.

[GitHub job-token commits do not recursively trigger workflows](https://docs.github.com/en/actions/concepts/security/github_token).
Generated-only output commits need no recursive recording or rendering.
