# Contributing

Use Poetry 2.5.1 and the committed lockfile:

```bash
poetry install --extras postgres
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
