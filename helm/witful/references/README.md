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
| [Local development](local/README.md) | Single-node PostgreSQL and generated Compose services for a disposable environment. | [local/values.yaml](local/values.yaml) |

Run `npm --prefix scripts/chart run generate` after changing annotated values,
then run the README contents hook. The same generator and drift check run in CI.
