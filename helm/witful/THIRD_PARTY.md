# Third-party chart schemas

`values.schema.json` includes the native `Cluster.spec` schema from CloudNativePG's
[CRD source at the reviewed chart release](https://github.com/cloudnative-pg/charts/blob/cloudnative-pg-v0.29.1/charts/cloudnative-pg/templates/crds/crds.yaml).
CloudNativePG Authors license it under Apache-2.0; the upstream license is retained
in [licenses/cloudnative-pg.txt](licenses/cloudnative-pg.txt).

The dependency version and repository are maintained in `Chart.yaml` and
`Chart.lock`. `scripts/chart/schema.py` reads that locked chart archive when
regenerating the values schema, so a dependency update also updates its schema.
Review upstream template/schema changes and the resulting generated diff together.
Helm validates structural types and constraints; Kubernetes and the running
operator additionally enforce admission rules, including CEL and webhooks.
