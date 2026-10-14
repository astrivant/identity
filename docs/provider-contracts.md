# Delivery provider contract tests

Delivery has two complementary test layers: synthetic unit cases for errors and
ordering, and real PyGithub/python-gitlab transports against local HTTP servers.
The HTTP tests validate their success responses against selected vendor OpenAPI
schemas before serving them. They exercise pagination, encoded GitLab namespaces,
inventory and exact-revision signature evidence without credentials or live writes.

## Versioned inputs and results

[The manifest](../scripts/ci/provider_contracts/data/manifest.json) owns immutable
vendor source revisions, source and snapshot SHA-256 digests, and selected GET
operations. The committed snapshots contain only success responses and their
referenced components; the generator preserves schema constraints and replaces email addresses inside
examples with reserved synthetic addresses. GitHub examples
supply structural fields around explicit synthetic scenario values. GitLab's
schemas validate the deliberately minimal scenarios already used in unit tests.

The independent [CI stage](../.github/workflows/stage-provider-contracts.yml)
checks out the caller's exact revision, installs the committed lockfile, regenerates
the snapshots in check mode, and runs the HTTP tests. Tag builds must additionally
resolve the current official specification branch heads through the SDKs, refresh
at those immutable commits, and pass the tests before publication. Resolution or
validation failure blocks release; there is no fallback to the older baseline. Required CI and release
publication require this stage to succeed. The `provider-contracts` artifact pairs
JUnit results with source revision, installed SDK/validator versions, lockfile
digest, vendor contract pins and the actual tested snapshots. Tag receipts also
record when the latest heads were observed. This means latest at that resolution
boundary, not a guarantee that upstream stops changing during the run. The release
source/tag is unchanged; the additional current-contract test inputs live in the
artifact. Its provenance file records inputs, not success;
a failed or interrupted run must not be interpreted as a passing result.

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
poetry run pytest -n 0 scripts/ci/tests/test_provider_contracts.py
poetry run python scripts/ci/provider_contracts/refresh.py --check
poetry run pre-commit run --all-files
```

To exercise the tag freshness gate locally, use `--latest` instead of explicit
revision overrides, then run the same tests. It resolves GitHub specification
`main` and GitLab specification `master`, records full commits and observation time,
and refreshes the local snapshots for review. It does not select or upgrade SDK
package versions; those remain governed by the committed lockfile.

Either revision override can be omitted to retain its committed pin. No override
means reproducible regeneration at existing pins. `--check` fetches those pins and
fails on source-byte or generated-output drift; it neither discovers newer versions
nor edits files. Downloads are bounded, public and unauthenticated. Unavailable
sources fail visibly rather than falling back to a stale success result.

Review endpoint/schema changes, explicit fixture adjustments, license changes and
SDK behavior together. Commit the manifest and generated snapshots in the same PR.
Refresh when updating either SDK or a supported server version, and review upstream
changes monthly. Pins make old results reproducible; the refresh procedure is what
keeps the reviewed baseline current. PR checks use committed pins. Tag checks resolve current heads first, then fetch
and test immutable revisions; they never silently accept older inputs.

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
