# Releases

CI uses the `vMAJOR.MINOR.PATCH` tag for package metadata before building.
Independent tests, source checks, PII scanning, and orchestration must pass
before publication. The release job downloads that run's verified wheel and
source distribution; it never uses a cached distribution or rebuilds it.

Select this repository for the organization `PYPI_API_TOKEN` Actions secret.
CI exposes it only as `POETRY_PYPI_TOKEN_PYPI` in the publishing step. Configure
the `pypi` environment for the intended tag deployment policy.

With authenticated `gh`, OpenSSL, and Cosign 3.x, run the setup helper:

```bash
bash scripts/release/setup-signing.sh --repo OWNER/REPO
```

It creates local protected key backups and sets `COSIGN_PRIVATE_KEY` and
`COSIGN_PASSWORD` in the explicitly selected repository. Reuse `--key-dir PATH`
after a partial upload; do not regenerate a new identity just to retry.

The pinned Cosign tool signs each final distribution and the SHA256SUMS manifest.
The release attaches distributions, signature bundles, public key, SHA-256
public-key fingerprint, signed manifest, SOURCE.json build provenance, and the
signed RELEASE.json contribution inventory.
The GitHub release remains a draft until PyPI publication succeeds. Already
published GitHub releases are immutable; publish a new version for new bytes.

Compare the fingerprint through a trusted channel before verification. A hash
verifies bytes; a trusted public key establishes the signing identity. The
release notes contain the exact consumer verification commands.


## Contributor notifications and change notes

The release pipeline prepares one immutable contribution inventory before signing.
A `What changed` section groups included merged PRs for consumers, followed by
`Release details`, which retains the existing installation and signature commands.
On a draft retry, the helper changes only its marked summary and preserves other
maintainer text. It refuses to rewrite a published release.

Maintainers classify PRs using the first applicable label in this order:

| PR label | Release-note heading |
| --- | --- |
| `release:breaking` | Breaking changes |
| `release:added` | Added |
| `release:changed` | Changed |
| `release:fixed` | Fixed |
| `release:security` | Security |
| `release:deprecated` | Deprecated / Removed |
| `release:docs` | Documentation / Maintenance |
| No category label | Other changes |

Write PR titles as concise consumer-facing descriptions. Include upgrade actions
and migration links in reviewed release details for breaking changes. The
`release:exclude` label excludes a PR from both the change summary and notifications;
review it for fully reverted contributions or changes that must not be announced.
The inventory represents merged contributions, not an automated analysis of net
behavior after reversions. Direct commits remain reachable through the full
comparison link without inventing a PR or recipient.

The prior baseline is the highest lower stable version whose commit is an ancestor
of this release. This supports backport branches without selecting an unrelated
newer release. Drafts and prereleases are excluded; the publisher currently accepts
stable versions only. An initial release includes all reachable history. Paginated
commit-to-PR associations support merge, squash and rebase merges; an incomplete
comparison fails instead of announcing partial coverage.

The separate [release feedback stage](../.github/workflows/stage-release-feedback.yml)
runs in the same logical CI workflow after publication. It verifies the complete
GitHub attachment set against the signed manifest and this run's build artifacts,
checks the signing fingerprint from the signing job, and downloads matching PyPI
files. Only then does it leave one persistent comment per PR/version, mentioning
the opener and linking the exact release. A deleted opener receives an unmentioned
contribution comment. Reporting has scoped PR-write permission and serialized
writers; no signing key or PyPI credential enters that job.

A lost response is reread before any later retry. Existing automation comments and
prior-version comments are preserved. Failed or uncertain PR outcomes are retained
in the `release-feedback` Actions artifact. Rerun the failed reporting job after
repairing its access or transient failure; do not rerun artifact publication to
repair a notification. A reporting failure leaves the verified release published
and the communication job unsuccessful. A skipped publisher fails the terminal
release check. No PR workflow sends release notifications.

## Preview and verification

The helper uses the locked [PyGithub SDK](https://pygithub.readthedocs.io/en/stable/),
including its paginated [comparison](https://pygithub.readthedocs.io/en/stable/github_objects/Comparison.html)
and [commit associations](https://pygithub.readthedocs.io/en/stable/github_objects/Commit.html).
It reads `GH_TOKEN`, falling back to `GITHUB_TOKEN`. Repository, tag and source
may come from `GITHUB_REPOSITORY`, `RELEASE_TAG` and `GITHUB_SHA`, or explicit flags.
Prepare an unpublished tagged candidate without remote writes:

```bash
python -m scripts.release.cli --repo OWNER/REPOSITORY --tag VERSION_TAG \
    --source COMMIT_SHA prepare --output .cache/release-preview
```

Inspect `RELEASE.json` and `release-notes.md` before publication. For an already
published release, use the original build artifacts and independently trusted
signing fingerprint to preview missing comments without posting:

```bash
python -m scripts.release.cli --repo OWNER/REPOSITORY --tag VERSION_TAG \
    --source COMMIT_SHA notify --built dist --download .cache/release-check \
    --fingerprint TRUSTED_SHA256 --receipt .cache/release-preview/receipt.json --dry-run
```

The download directory must be new. Each asset is bounded to 512 MiB, matching
this package-oriented verification budget. The contributor inventory is signed
inside the checksum manifest; it is not recomputed from mutable PR metadata during
notification retries. Successful tests establish the exercised contracts, while
actual tag publication is required to verify the hosted reporting path.

Run `pytest -n 0 tests/releases tests/checkpoints` for focused verification. API tests
use real SDK HTTP traffic against a loopback mock with responses validated against
committed vendor schemas. Refresh and review those schemas with
`python scripts/ci/provider_contracts/refresh.py --latest`; the existing PR/tag
freshness gate enforces current contracts. The mocks validate transport and schemas,
not all GitHub service behavior. Cryptographic process-result tests use explicit
test doubles; real signed artifacts are verified by the tag stage before comments.
