# Engineering standards review

This review starts from `67c86d16ec24b8d9979856aa46f2f1d582cc448f` (Witful
v0.3.1) and proposes a bounded set of delivery and documentation fixes. It is
not a declaration that every standard is satisfied. Reviewers should assess
this patch separately from the release and publication follow-ups below.
No live branch policy, release, credential, or deployment is changed by this PR.

## Changes proposed for review

- Add a stable `Required CI` merge gate that rejects incomplete, failed, skipped,
  or cancelled producer results. Negative-path tests bind the workflow and
  proposed protection settings to the same complete producer set.
- Require the GitHub Actions app for that check, retain one independent approval
  and administrator bypass, and propose conversation resolution plus protection
  against force pushes and branch deletion.
- Run pinned offline CODEOWNERS validation and Markdown math/Mermaid checks in
  pre-commit and CI. Validate the checker with positive and negative fixtures;
  preserve the public source attribution and license.
- Run the development image as the same non-root identity as production. Hosted
  orchestration builds and smoke-tests both targets and their writable directories.
- Include environment-install logic in the executable Python cache key.
- Measure package line/branch coverage in CI, retain its source-bound report, and
  publish a measured README badge through signed API commits on an artifact branch.
  This gap was missed in the initial review and corrected during maintainer feedback;
  PyPI and license badges were removed as requested.
- Document real runtime inputs and hosted agent-skill access, and give each Helm
  configuration reference its own values file and generated parameter guide.

## Evidence and coverage

| Surface | Evidence and disposition |
| --- | --- |
| Source and package | Locked Poetry environment and strict Ruff, mypy, Google/typed docstring, SQL, and shell checks. Baseline: 236 tests passed; eight PostgreSQL cases skipped locally. No local database was started. |
| Functional boundaries | Inspected append-only journals, explicit PostgreSQL selection, read-only remote consumers, encrypted transport, and completion coverage/freshness tests. These contracts have synthetic regression coverage; they do not establish behavior against every external service. |
| Architecture and lifecycle | CLI and bounded batch jobs, with explicit source/configuration selection. Both image targets retain Tini; chart workers have non-root, read-only security contexts and bounded job duration. No new persistent HTTP service or queue is introduced, so a Flask metrics API is outside this patch. |
| Documentation | Runtime inputs checked against argument/environment readers. Existing automatic README TOCs retained; Helm tables/schema regenerated from annotated values. New syntax checks parse equations and diagrams; hosted visual rendering is not proved by parsing. |
| Coverage | CI now measures the package and prepares report/badge artifacts. The badge publisher is covered by API fixtures; first live publication requires the post-merge main event. |
| CI | Independent source producers remain parallel. Gate tests exercise every producer's failure, cancellation, and skip state, plus missing/malformed results. Hosted results for this PR are the authority for image builds and PostgreSQL integration. |
| Live protection | At the review baseline, main required five named checks, strict freshness, and one approval, with administrator bypass allowed. Checks had no app binding. Proposed settings require a separately authorized host reconciliation after review. |
| Ownership | Existing scoped owners preserved and extended to this patch. GitHub reported no CODEOWNERS parse errors and the listed maintainer had admin access. Local lint checks syntax and paths, not ongoing membership. |
| Dependencies | Reused public tooling and verified current registry versions before adoption. Mermaid updated to 12.2.0 with its npm lockfile; the documentation dependency audit reported no known vulnerabilities at installation. This is not a complete dependency/image vulnerability assessment. |
| Current release | v0.3.1's signed wheel, sdist, checksum manifest, source provenance, and independently trusted key fingerprint were verified during its release; PyPI hashes and isolated installation were checked. [Tag CI](https://github.com/astrivant/identity/actions/runs/38478362871) passed. This prior observation does not prove future release failure paths. |
| Plots and state | Public synthetic example refresh is already proposed in [PR #12](https://github.com/astrivant/identity/pull/12). Do not duplicate it or substitute personal records for fixtures. That work and a successful main run are still needed to establish ongoing refresh. |
| Deployment | Chart and Compose are local build/deployment inputs. No cluster, production database, load profile, or shutdown-under-load experiment was exercised for this audit. |

## Remaining work, in priority order

1. **Release failure paths and registry identity.** The publisher signs and checks
   local bytes but has no independent terminal check proving the public release
   exists when publication is skipped. Its PyPI `--skip-existing` path lacks an
   exact file-set/hash preflight and readback. A reused local `dist/` or release
   directory can also retain stale files. Add fresh staging, immutable-source
   checks, retry-safe registry comparison, downloaded artifact verification, and
   regression fixtures for missing, mismatched, skipped, failed, and successful
   publication before treating the release contract as complete.
2. **Signed generated commits.** The private-copy publication helper invokes Git
   with a bot name/email but does not establish a registered signing identity.
   Adopt a verified API/bot signing path and test retry/concurrent-main behavior.
   A local developer's signing configuration cannot establish runner verification.
3. **Synthetic refresh and protected-branch publication.** Review PR #12 and verify
   regenerated outputs against their exact committed source. Protected main needs
   reviewed plot updates rather than an assumed direct-push bypass.
4. **Compatibility and security breadth.** CI currently exercises Python 3.14,
   while package metadata supports 3.12 and 3.13 too. Add supported-runtime
   coverage, dependency/image vulnerability checks, and a reviewed full pin audit.
   Retain the explicit Python 3.14.1 exclusion and existing compatibility constraints.
5. **Distribution boundaries.** Chart/image versions still describe a local-build
   workflow and are not published release deliverables. Decide whether to ship
   them as signed versioned artifacts before adding registry publication. Clarify
   the version relationship and validate installation from those artifacts.

The PR body carries the final candidate's local and hosted validation. A green
aggregate check does not close these explicitly unimplemented follow-ups.

## Reproducing the review checks

With the locked development environment, Node.js 26.10.0, Helm, Cosign, and
standard shell tools installed:

```bash
poetry check --lock
npm ci --prefix scripts/documentation --ignore-scripts --no-fund
npm ci --prefix scripts/chart --ignore-scripts --no-fund
npm --prefix scripts/documentation test
npm --prefix scripts/chart run generate
poetry run pytest -n 4 pkg/witful scripts/ci/tests
poetry run pre-commit run --all-files
```

Set `WITFUL_TEST_DATABASE_URL` only for an explicitly selected test database.
The CI orchestration job supplies Docker/Composer validation. Hook-generated edits
must be reviewed and rerun to a clean pass before publication.

The protection proposal follows [GitHub's protected-branch contract](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
The registry follow-up can compare files through the [PyPI JSON API](https://docs.pypi.org/api/json/).

The repository privacy gate separately reviews the public logo by exact path and
SHA-256 digest in `scripts/ci/checks/privacy.py`. The PNG has no metadata and was
visually inspected as an unlabeled graph mark. Changed bytes require another
review. Other binary files still fail closed; the package privacy scanner remains
unchanged. Regression checks cover modified, renamed and staged asset bytes.
