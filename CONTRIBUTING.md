# Contributing

Use Poetry 2.5.1 and the committed lockfile:

```bash
poetry install --extras postgres --extras sapience
poetry run pre-commit install
poetry run pytest -n 4
poetry run pre-commit run --all-files
```

Keep Python implementation and tests under `pkg/witful/`. Use strict types,
attrs/cattrs contracts, multiline Google docstrings, and pure transformations
with explicit inputs. Add focused regressions for behavior changes. Tests use
synthetic data; never copy personal records into fixtures. Live PostgreSQL tests
use `WITFUL_TEST_DATABASE_URL` and skip when it is not configured locally.

Independent CI checks start in parallel: Python tests, lint, PII, distributions,
and orchestration. Tag publication consumes the verified distributions after
all checks pass; it does not rebuild them. See [release operations](docs/releases.md).

Non-Python pins live beside their consumers: action commit SHAs and documented
versions in `.github/workflows/ci.yml`; Python/PostgreSQL image digests in the
Dockerfile and chart; Composer commit in CI and pre-commit; Bitnami README/schema
generator 2.7.2 (with glob 13.0.6 using its compatible synchronous API) in `scripts/chart/package-lock.json`; Poetry 2.5.1 in CI/Docker.
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

Sapience adapter tests cover deterministic projection and rejection of malformed
responses without model calls. Run `pytest pkg/witful/sapience/tests -n 2` for a
focused check. For cross-project protocol verification, launch the Sapience fork's
`tests/stdio_fixture.py` with its own Python environment as `--server` and that script
as `--server-arg`; set `SAPIENCE_DATA_DIR` to a temporary directory and use a synthetic
Witful collection. Repeat `sync`, verify readback, and test `propose` against an empty
namespace to avoid a synthesis request. Never substitute personal records into fixtures.

## Session and process lifecycle

[Multisleeving](docs/multisleeving.md) uses private worktrees, signed checkpoints,
and an explicit remote-ancestry close gate. Its focused tests use temporary local
Git remotes, ephemeral SSH signing keys, synthetic encrypted collections, and real
TERM/INT/HUP signals. No model provider or live Kubernetes cluster is required.

The Dockerfile pins Debian Trixie's Tini to `0.19.0-3+b8`, verified for amd64 and
arm64 in the [Debian package index](https://packages.debian.org/trixie/tini).
Both image targets and the chart/derived Compose entrypoint retain Tini. Regenerate
Compose when changing the chart; do not patch its generated entrypoint directly.
