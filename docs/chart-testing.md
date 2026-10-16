# Helm property tests

Identity requires hypothesis-helm alongside its chart examples and schema checks.
The independent [property-test stage](../.github/workflows/stage-helm-properties.yml)
runs on PRs, main and release tags. `Required CI` and release publication require
its success, including when another job fails or is skipped.

## Tested contract

The generated suite varies synchronization worker counts, the Job lifecycle object
and its fields, anti-affinity presets and the topology key. It renders the real
chart with its locked dependencies and validates the resulting Kubernetes resources.
The [generation policy](../scripts/chart/hypothesis.yaml) includes worker counts
above the former limit. Its finite worker sample bounds test cost; it does not
limit the chart's supported values. Native Helm is the renderer for this chart,
which has no random template functions.

The stage selects these named properties explicitly. It does not test every value
combination or certify PostgreSQL operator reconciliation. Existing
[chart tests](../scripts/chart/tests/) retain the controller, scheduler, database,
secret-mount, invalid-input and HA assertions. No cluster or real credentials are
used. Values and rendered manifests can appear in reports; use synthetic inputs.

## Reproduce and inspect failures

Use Python 3.13 or newer and the Helm version selected in the stage. Install the
same immutable tool revision in its isolated Helm-plugin environment:

```bash
revision="$(awk '/uses: astrivant\/hypothesis-helm@/ {split($3, pin, "@"); print pin[2]}' .github/workflows/stage-helm-properties.yml)"
PYTHON=python3.13 helm plugin install https://github.com/astrivant/hypothesis-helm --version "$revision"
bash scripts/chart/dependencies.sh
helm hypothesis schemas --schema-cache-dir .cache/helm-schemas
helm hypothesis test helm/witful --paths \
  --match 'test_sync_workers_ or test_sync_job_ or test_sync_scheduling_podAntiAffinityPreset_ or test_sync_scheduling_topologyKey_' \
  --config scripts/chart/hypothesis.yaml --max-depth 0 --seed 20261015 --jobs 2 --timeout 15 \
  --validate-schemas --strict --schema-cache-dir .cache/helm-schemas \
  --no-cache --artifact-dir .cache/helm-properties
```

If the plugin is already installed, update it to the reviewed revision before
comparing results. The action pin identifies the tool source; its upstream plugin
installer resolves package dependencies, so it is not a complete transitive lock.
Keep this environment separate from Witful's locked application environment.

CI retains generated tests, path selection, constraints, source metadata and JUnit
in the `helm-properties` artifact family for 14 days, including test failures.
Inspect minimized failing inputs and the selected schema/tool metadata before
changing the chart. Reproduce with the recorded seed; keep a regression for the
contract that failed. Setup failures may precede report creation and remain visible
in the job log. A failed, cancelled, missing or skipped stage blocks acceptance.

To extend coverage, add supported profiles or properties with an explicit test
purpose and runtime budget. Preserve findings instead of suppressing them to make
CI green. Refer to the [upstream action documentation](https://github.com/astrivant/hypothesis-helm/blob/main/docs/ci/action.md)
for the distinction between single-chart properties and recursive chart discovery.
