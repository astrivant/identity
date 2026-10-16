# Build and verify Witful containers

Witful's [Dockerfile](../services/witful/Dockerfile) builds the production CLI and
an editable development environment from the same Poetry lockfile. The build
context is the repository root. Docker Engine with BuildKit and the Compose plugin
are required for these commands.

## Build the application

```bash
docker build --file services/witful/Dockerfile --target production \
  --tag witful:local --iidfile /tmp/witful-production.id .
docker run --pull=never --rm witful:local --help
```

The default final target is production. Git and SSH support collection operations;
Tini starts as PID 1 and forwards signals to the process group. Both targets use
UID/GID 10001, SIGTERM, and private working storage under `/run/witful`.

| Stage | Responsibility |
| --- | --- |
| `base` | Pinned interpreter, runtime OS tools, non-root identity and image metadata |
| `tooling` | Separate Poetry and application environments; package metadata and lockfile |
| `dependencies` | Locked runtime dependencies and the `postgres` and `native` extras |
| `wheel` | Build and install the application wheel without resolving dependencies again |
| `development` | Locked development tools and editable source under `/build/pkg` |
| `production` | Runtime base plus the installed application environment; no build tree or Poetry |

Dependency installation precedes application source copies. BuildKit cache mounts
retain downloaded packages outside the image layers. Keep the build cache within
your build system's trust boundary. The `.dockerignore` allowlist admits package
inputs and excludes collection records, credentials, Git metadata and test caches.

Interpreter, OS package and Poetry pins are maintained in the Dockerfile. The
interpreter minor follows the source CI runtime. CI supplies `VCS_REF` from its
source commit; local builds may pass `--build-arg VCS_REF=COMMIT_SHA` for a clean
checkout. An image built from uncommitted files does not represent that commit.
The optional [CodeGraph worker](codegraphs.md) has its own image and build context
under `services/codegraph/`.

## Develop against editable source

```bash
docker compose -f services/compose.development.yaml --profile development \
  run --build --rm development --help
```

This development-only Compose service mounts `pkg/` read-only at `/build/pkg`.
Edits made on the host are visible to the editable installation immediately.
It starts no database or broker and has no network access. The target itself owns
its build directory and application environment and includes Poetry and pytest;
its development tools do not enter production. Use the
[generated local service stack](storage.md) for database-backed operations.

## Verify the exact images

```bash
docker build --file services/witful/Dockerfile --target development \
  --tag witful:development --iidfile /tmp/witful-development.id .
PRODUCTION_IMAGE="$(cat /tmp/witful-production.id)" \
DEVELOPMENT_IMAGE="$(cat /tmp/witful-development.id)" \
  bash scripts/ci/checks/images.sh
```

The same CI script accepts only local image IDs. It checks the CLI, Tini, UID/GID,
SQL resources, writable working paths, production dependency isolation and editable
development imports. Production checks use a read-only root filesystem with explicit
temporary working mounts, no network, no capabilities and no privilege escalation.
These are synthetic image checks, not admission of a host for private collection work;
[protected storage](data-protection.md) still applies to real records.

`pre-commit run dockerfile-check --all-files` runs Docker's maintained build checks
for both application targets and the optional worker. CI runs that same hook before
building images. The generated local Compose stack names the application Dockerfile
explicitly; edit its profile and regenerate it when changing the build path.

See Docker's [multi-stage build guidance](https://docs.docker.com/build/building/multi-stage/)
and [cache guidance](https://docs.docker.com/build/cache/optimize/) for the stage and
cache mechanisms. Tini's [process-group behavior](https://github.com/krallin/tini#process-group-killing)
does not replace application-owned cancellation and cleanup.
