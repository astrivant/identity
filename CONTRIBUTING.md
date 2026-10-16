# Contributing

Use Poetry 2.5.1 and the committed lockfile:

```bash
poetry install --extras postgres
poetry run pre-commit install
poetry run pytest -n 4 pkg/witful scripts/ci/tests --cov=witful --cov-branch --cov-report=term-missing
poetry run pre-commit run --all-files
```

ShellCheck and shfmt validate standalone shell scripts. The pinned Actionlint hook
also validates every workflow and sends inline `run:` shell to ShellCheck; missing
ShellCheck fails the hook. CI runs this same hook with
`pre-commit run actionlint --all-files`. Pre-commit builds Actionlint using Go
(the minimum is defined in its pinned upstream `go.mod`). Keep the project environment
on `PATH` so local hooks and CI use the locked ShellCheck installation.

Quote scalar command substitutions, including assignment values, for consistent
readability: `value="$(command)"`. Plain Bash assignments already suppress word
splitting and glob expansion; this style is stricter than ShellCheck's required
quoting checks. Prefer `[ ... ]` for simple tests and retain `[[ ... ]]` for
pattern/regex matching. Preserve behavior when changing syntax.

Register named Bash functions as trap handlers, including in CI. Give each handler
an intent comment and typed signature describing its inputs or owned state, cleanup
scope, and exit contract. Capture the incoming status before any other command,
disable a trap before explicitly exiting its handler, and keep cleanup failures
visible. These EXIT handlers preserve an existing failure and exit with status 1 if
cleanup alone fails. Exercise success, command failure, and cleanup failure paths;
document signal handling separately when a script installs signal traps.

Keep Python implementation and tests under `pkg/witful/`. Use strict types,
attrs/cattrs contracts, multiline Google docstrings, and pure transformations
with explicit inputs. Add focused regressions for behavior changes. Tests use
synthetic data; never copy personal records into fixtures. Live PostgreSQL tests
use `WITFUL_TEST_DATABASE_URL` and skip when it is not configured locally.

Use NetworkX consistently for graph operations, including cycle validation and
prerequisite ordering. Keep the graph vocabulary uniform across modules. A
`source requires target` relation becomes a `target -> source` edge for ordering;
retain isolated nodes and canonical-ID tie breaks when constructing selected graphs.

Define custom package exceptions in `witful.exceptions` and import them directly
from there in implementation code and tests. Keep operational functions, such as
`require_protected`, in their domain modules. The exception module has no domain
imports, so low-level callers can import failure types without circular dependencies.
Existing storage, protection, and sleeve-model exception paths remain aliases to
the same classes for compatibility; preserve their base types and catch behavior.

See [measured coverage](#measured-coverage) for the combined line/branch report,
provenance, and verified API publication contract.

Independent CI checks start in parallel: Python tests, lint, PII, Trivy, distributions,
and orchestration. Tag publication consumes the verified distributions after
all checks pass; it does not rebuild them. See [release operations](docs/releases.md).

Non-Python pins live beside their consumers: action commit SHAs and documented
versions in `.github/workflows/ci.yml`; Python/PostgreSQL image digests in the
Dockerfile and chart; Composer commit in CI and pre-commit; Bitnami README/schema
generator 2.7.2 (with glob 13.0.6 using its compatible synchronous API) in `scripts/chart/package-lock.json`; Poetry 2.5.1 in CI/Docker.
Coverage publication uses the pinned GitHub SDK action in the workflow.
The release signing job pins Cosign. Update consumer and lock/schema outputs
together. Check JavaScript actions' own Node runtime when upgrading.

The automatic README contents hook includes nested READMEs and at most three
levels. Chart README/schema output comes from annotated values. Regenerate
outputs instead of editing generated tables or schemas directly.


Private-copy CI lives in the same workflow and uses only synthetic fixtures in tests.
The crypto integration test needs Cosign 3.x, OpenSSL, and ssh-keygen locally; CI
installs the pinned Cosign version before tests. Never test setup against a real
repository or project secrets as part of an ordinary test run. See
[private collection boundaries](docs/private-collections.md) before changing the
archive allowlist, trust pins, or encrypted transport. Cryptography is pinned through
Poetry; Cosign pins remain beside both its test and pipeline consumers.

## Session and process lifecycle

[Multisleeving](docs/multisleeving.md) uses private worktrees, signed checkpoints,
and an explicit remote-ancestry close gate. Its focused tests use temporary local
Git remotes, ephemeral SSH signing keys, synthetic encrypted collections, and real
TERM/INT/HUP signals. No model provider or live Kubernetes cluster is required.

The Dockerfile pins Debian Trixie's Tini to `0.19.0-3+b8`, verified for amd64 and
arm64 in the [Debian package index](https://packages.debian.org/trixie/tini).
Both image targets and the chart/derived Compose entrypoint retain Tini. Regenerate
Compose when changing the chart; do not patch its generated entrypoint directly.


## Observed instance contracts

Instance tests use synthetic native collections and independent writer processes.
Run `pytest pkg/witful/instances/tests -n 2` when changing boundaries, reconciliation,
source allowlists, or instance plots. The development-only OpenTelemetry protobuf
package validates the emitted local OTLP/JSON envelope; production has no exporter
or new OpenTelemetry dependency. Preserve native schema/hash compatibility, exact
journal prefixes, task compare-and-set updates, and unknown/gap semantics. Inspect
empty, baseline, zero-change, changing, and overlapping-window renders before
publishing renderer changes. See [the instance contract](docs/instances.md).

## Documentation and merge checks

Install Node.js 26.10.0, then run
`npm ci --prefix scripts/documentation --ignore-scripts --no-fund` before the
hooks. The pinned CODEOWNERS hook bootstraps its own Go environment on first use.
Run `npm --prefix scripts/documentation test` for the syntax checker regressions
and `pytest scripts/ci/tests` for missing, skipped, failed, and cancelled CI results.

Run `npm --prefix scripts/documentation run format` after editing the root README.
Pre-commit and CI require that pinned Prettier output and run the same
`npm --prefix scripts/documentation run markdown:lint` structural checks over all
Git-owned Markdown, including nested READMEs. Generated documentation retains its
generator's formatting. The GFM regression check rejects table rows separated from
their header by a blank line; preview changed tables on GitHub as well as linting.
The [markdownlint rules](https://github.com/DavidAnson/markdownlint/blob/main/doc/Rules.md)
and [Prettier options](https://prettier.io/docs/options) describe the maintained tools.

The math check accepts a strict KaTeX subset, hosted Markdown dollar delimiters,
and fenced Mermaid diagrams. It checks syntax, so preview changed diagrams and
equations in their intended renderer as well. Escape literal dollars in prose.
CODEOWNERS checks are offline; owner permissions remain a separate host check.

`Required CI` joins all required validation producers without serializing them.
The proposed main policy binds that check to GitHub Actions, retains one independent
approval and administrator bypass, and requires resolved conversations. A maintainer
must reconcile the live policy after this PR is reviewed; changing YAML alone does
not enforce it. An agent still needs approval for a particular administrator merge.

See the [engineering standards review](docs/engineering-review.md) for checked
contracts, evidence limits, and follow-up work. No tag or release is part of that review.

## Measured coverage

Projects with Helm charts also require hypothesis-helm property tests. Follow
[the chart testing guide](docs/chart-testing.md) for the tested domains, local
reproduction and CI failure artifacts. These supplement the existing chart examples.

The Python test job combines pytest-xdist workers through pytest-cov and measures
line and branch coverage for `witful`, excluding only test modules. It retains
JSON, XML, raw coverage data, and a badge/provenance pair in the `python-coverage`
artifact for 14 days. The README badge shows the combined line/branch percentage;
it is evidence of exercised code, not correctness or a replacement for assertions.

Every successful public-main test and learning run updates `badges/coverage.svg` and
`badges/coverage.json` on `gh-pages` through GitHub's signed commit API. The latter
records the measured source commit, scope, counts, and full report digest. The
same atomic commit publishes all four synthetic learning SVG/PNG figures under
`badges/continual-learning/`, preserving their exact binary bytes. The publisher
checks the latest main source, uses an expected branch head to reject concurrent
writers, verifies GitHub's commit signature status, and reads back the
exact published bytes. No external coverage account, secret, or main-branch bypass
is required. PRs retain artifacts without publishing; the badge becomes available
after the first successful main run following merge. Failed tests keep the last
successful main measurement, whose source remains visible in the linked metadata.

Run `poetry run pytest -n 4 --cov=witful --cov-branch --cov-report=term-missing`
locally. `npm --prefix scripts/documentation test` includes the publisher's
bootstrap, stale-source, conflict, signature, readback, and malformed-input cases.

## Continual-learning examples

The independent `learning` job renders only the packaged synthetic fixture using
`witful reflection example`. Successful main runs publish its plots alongside the
coverage badge on `gh-pages`; no personal collection or model service is accessed.
Review renderer changes locally with `witful reflection example --output-dir
.cache/continual-learning`. Preserve the question subtitles and explicit synthetic
labels. Reflection tests use temporary Git histories and cover cadence boundaries,
retry identity, provenance, unknown outcomes, and deterministic output.

## Command and provider composition

Declare CLI arguments in `pkg/witful/commands/`, register the domain with the
immutable root builder, and expose `execute(args, parser)` in its runtime module.
Reuse the declaration from standalone entrypoints; parse once at each entrypoint,
without command-name tests against `sys.argv`. Keep parser imports lightweight.
Exercise public help, input errors, legacy syntax and selected runtime imports.

Delivery providers implement one interface using the maintained Python SDKs.
Keep host-specific metadata in the backend and shared Git lifecycle in orchestration.
Test the real SDK parsers with synthetic HTTP responses, as well as signed local
Git histories; fixture passes do not establish live host publication.
