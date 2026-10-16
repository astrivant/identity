# Chart configuration references

<!-- toc:start -->

**Table of contents**

- [Chart configuration references](#chart-configuration-references)

<!-- toc:end -->

Use one reviewed values override with the main chart's defaults. Each reference
keeps its values and generated parameter documentation together. Credentials and
private source records remain runtime inputs.

| Reference | Purpose | Values |
| --- | --- | --- |
| [Resilient synchronization](ha/README.md) | Three workers separated across nodes against an external HA PostgreSQL endpoint. | [ha/values.yaml](ha/values.yaml) |
| [Operator-managed PostgreSQL](postgresql/README.md) | Three PostgreSQL instances with required node separation, using an existing or optional bundled CloudNativePG operator. | [postgresql/values.yaml](postgresql/values.yaml) |
| [Protected native controller](native/README.md) | Explicit native PostgreSQL HA with separate authority/key services and validated ConfigMap. | [native/values.yaml](native/values.yaml) |
| [Isolated projection gateway](projection/README.md) | Separate single-writer remote publication with permit-only decryption, repository-scoped SSH and explicit network policy. | [projection/values.yaml](projection/values.yaml) |
| [Local development](local/README.md) | One operator-managed instance or explicit local Compose substitution for a disposable environment. | [local/values.yaml](local/values.yaml) |

Run `bash scripts/chart/dependencies.sh`, then `npm --prefix scripts/chart run generate` after changing annotated values,
then run the README contents hook. The same generator and drift check run in CI.
