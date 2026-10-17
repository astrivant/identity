# Delivery provider contract tests

Delivery has two complementary test layers: synthetic unit cases for errors and
ordering, and real PyGithub/python-gitlab transports against local HTTP servers.
The HTTP tests validate their success responses against selected vendor OpenAPI
schemas before serving them. They exercise pagination, encoded GitLab namespaces,
inventory and exact-revision signature evidence without credentials or live writes.
The same versioned contract stage covers release-range selection, PR comments and
release assets through the real GitHub SDK. Lost-response and permission failures
are explicit synthetic transport scenarios, not claims about live service behavior.

## Versioned inputs and results

[The manifest](../scripts/ci/provider_contracts/data/manifest.json) owns immutable
vendor source revisions, source and snapshot SHA-256 digests, and selected GET
operations. The committed snapshots contain only success responses and their
referenced components; the generator preserves schema constraints and replaces email addresses inside
examples with reserved synthetic addresses. GitHub examples
supply structural fields around explicit synthetic scenario values. GitLab's
schemas validate the deliberately minimal scenarios already used in unit tests.

The independent [CI stage](../.github/workflows/stage-provider-contracts.yml)
checks out the caller's exact revision and installs the committed lockfile. Every
PR, main and tag run resolves the latest commit affecting each specification file
on its official branch and refreshes the selected snapshots at those immutable
revisions before running the compatibility suite. A newer revision or metadata-only
change does not fail CI. Lookup, download, integrity, unsupported dialect and
compatibility failures still block acceptance. SDK packages remain locked.

The `provider-contracts` artifact retains the exact renewed snapshots, current
observation, source revision, installed SDK/validator versions, lock digest and
JUnit results. Downstream jobs download that same-run artifact instead of resolving
upstream again. This durable handoff is required; an evictable dependency cache is
not a substitute for the tested inputs. Independent source checks remain parallel.

After successful main verification, `generated-updates` checks the artifact's
source, lock and file digests, then compares the selected contracts with the baseline.
New upstream commits that leave the selected snapshots and endpoint configuration
unchanged stay in the run artifact; they do not create a provenance-only baseline PR.
The committed pins still reproduce the last reviewed baseline, while the artifact
records the latest inputs actually tested in this run. When selected contracts change,
the job proposes the three renewed JSON files in a GitHub-signed update branch.
Each source and changed bundle gets an idempotent proposal, and an older run cannot replace newer main state. No release
tag or distribution is rewritten. Tag runs test current contracts but never write
back; main owns baseline maintenance.

The update joins main through its normal required review and CI. When repository
settings permit Actions to create PRs, the job opens a PR and explicitly dispatches
CI for its branch, since built-in-token writes do not trigger ordinary PR/push
workflows. If that policy is disabled, the job preserves the verified branch and
provides a compare link for a maintainer to open it. It never approves, merges,
force-pushes or changes repository permissions. Superseded proposals can be closed
by their reviewer. Fork PRs and tags never receive publication credentials.

Refresh locally with `--latest` and run the same tests when reviewing a provider or
SDK change. The optional `--check --latest` command diagnoses drift without writing;
CI uses refresh-and-test so metadata drift alone cannot prevent those tests.
Provenance records inputs, not proof of test success. Latest is the observed
boundary for that run, not a guarantee about future upstream activity.

The servers bind ephemeral loopback ports. Test clients reject external destinations
and authentication headers. The test owns server shutdown, thread joining and SDK
session closure. Existing transport-mocked unit tests remain useful for deliberate
errors that do not represent successful vendor responses.

## Refresh the contracts

Install development dependencies with `poetry install` using a supported Python.
Select and review full commit IDs in the official
[GitHub REST descriptions](https://github.com/github/rest-api-description) and
[GitLab OpenAPI source](https://gitlab.com/gitlab-org/gitlab/-/blob/master/doc/api/openapi/openapi_v3.yaml).
Then propose updated snapshots:

```bash
poetry run python scripts/ci/provider_contracts/refresh.py \
    --github-ref REVIEWED_GITHUB_SPEC_SHA --gitlab-ref REVIEWED_GITLAB_SPEC_SHA
poetry run pytest -n 0 scripts/ci/tests/test_provider_contracts.py tests/provider_contracts tests/releases
poetry run python scripts/ci/provider_contracts/refresh.py --check
poetry run pre-commit run --all-files
```

To prepare the current inputs, use `--latest` instead of explicit revision overrides,
then run the same tests and `refresh.py --check` to verify the selected pins. It resolves the latest
specification-file commits on GitHub `main` and GitLab `master`, records those
full commits, retaining observation time separately when `--observation` is supplied,
and refreshes the local snapshots for review. It does not select or upgrade SDK
package versions; those remain governed by the committed lockfile.

Either revision override can be omitted to retain its committed pin. No override
means reproducible regeneration at existing pins. `--check` fetches those pins and
fails on source-byte or generated-output drift; it neither discovers newer versions
nor edits files. Specification downloads remain bounded, public and unauthenticated.
GitHub metadata lookup uses `GH_TOKEN`, then `GITHUB_TOKEN`, when explicitly provided;
otherwise local lookup remains anonymous. CI supplies its existing token only to the
refresh step with `contents: read`. The token is confined to the GitHub SDK and is
never passed to GitLab, specification downloads, observation artifacts or mock tests.
The SDK requests one commit and avoids an extra repository-metadata lookup.

This avoids relying on the shared runner IP's [anonymous GitHub quota](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api).
No new secret or permission is needed; the workflow uses GitHub's
[built-in authentication](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token).
The locked SDK retries GET metadata requests at most twice. It interprets
`X-RateLimit-Reset` and secondary-limit responses; urllib3 parses `Retry-After`,
including HTTP dates. A small adapter adds up to one second of random jitter after
the selected minimum and applies a 120-second maximum to each server-directed wait.
A longer delay fails the gate for a later rerun instead of retrying before the
server permits it. Total retry sleep is bounded at 242 seconds per request, in
addition to the existing request timeout and job timeout.

Permanent authentication/permission failures, exhausted retries and unavailable
sources still block the gate. Credentials never fall back to anonymous access,
and failures never accept stale snapshots. Loopback HTTP regressions exercise the
real SDK retry transport with deterministic clocks and sleep capture; they do not
claim live quota-exhaustion coverage.

Review endpoint/schema changes, explicit fixture adjustments, license changes and
SDK behavior together. Commit the manifest and generated snapshots in the same PR
when the selected contracts change. Unrelated feature PRs do not need baseline
refresh commits: CI already records and tests their latest upstream observations.
Refresh when updating either SDK or a supported server version, and review upstream
changes monthly. Pins make old results reproducible; the refresh procedure is what
keeps the reviewed baseline current. PR, main and tag checks all test the latest observed specification-file revisions;
main retains successful renewals for subsequent reviews.

## Coverage boundaries

A mock server validates the behavior we model. These checks validate response
shapes and actual SDK transport/parsing, not server authorization, rate limits,
request-parameter validation, every error response or Git hosting behavior.
They do not run GitHub or GitLab, and the specification revision is not a claim
that a particular deployed server version passed integration tests.

Current explicit gaps and fixture corrections:

- PyGithub's `Commit.get_statuses()` reads a legacy `/statuses/{sha}` alias. The
  pinned GitHub description documents the GET collection at
  `/commits/{ref}/statuses`; the HTTP test explicitly maps the alias to that response
  schema. It does not prove the undocumented alias remains available upstream.
- The pinned GitLab commit-signature schema does not declare the flattened
  `verification_status` field the SDK consumes. The synthetic assertion covers our
  handling, while the schema cannot validate that field's upstream contract.
- Some GitHub examples omit required fields in repositories, labels, teams and
  commit files. The HTTP scenario supplies nullable repository languages and
  intentionally empty unrelated collections. It retains the vendor's required-field
  checks. Example provenance alone is not schema validation.

[GitHub Actions supports service containers](https://docs.github.com/en/actions/tutorials/use-containerized-services/use-docker-service-containers).
[GitLab supplies Docker images](https://docs.gitlab.com/install/docker/installation/),
but a running platform requires database, repository and authentication setup.
[GitHub Enterprise Server is a virtual appliance](https://docs.github.com/en/enterprise-server@latest/admin/overview/system-overview),
not an equivalent lightweight Docker service. This stage uses bounded local mocks;
real-platform integration remains a separate, explicit validation scope. Any future
service lane should pin images by version and digest and retain its setup and result
provenance alongside the application revision.
