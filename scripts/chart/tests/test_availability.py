"""
Exercise the chart's HA placement, override propagation and rejected configurations.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from jsonschema import Draft7Validator

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "helm/witful"


def render(values: dict[str, object], *, release: str = "witful") -> subprocess.CompletedProcess[str]:
    """
    Render an override without touching source values or a Kubernetes cluster.

    Args:
        values (dict[str, object]): Operator-supplied values layered over defaults.
        release (str): Release name used for resource ownership and placement.

    Returns:
        subprocess.CompletedProcess[str]: Helm status and output for positive or negative assertions.
    """
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "values.json"
        path.write_text(json.dumps(values))
        return subprocess.run(
            ["helm", "template", release, str(_CHART), "--values", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )


class AvailabilityContracts(unittest.TestCase):
    """
    Verify failure-domain placement and configuration boundaries for one-shot workers.
    """

    def test_ha_reference_scopes_placement_to_job(self) -> None:
        """
        Keep retained Jobs and other releases outside generated placement selectors.

        Returns:
            None: The HA reference separates workers on nodes and prefers zone spreading.
        """
        values = yaml.safe_load((_CHART / "references/ha/values.yaml").read_text())
        for release in ("witful", "another-collection"):
            with self.subTest(release=release):
                result = render(values, release=release)
                assert result.returncode == 0, result.stderr
                documents = list(yaml.safe_load_all(result.stdout))
                assert [item["kind"] for item in documents] == ["Job"]
                job = documents[0]
                assert job["spec"]["parallelism"] == job["spec"]["completions"] == 3
                labels = job["spec"]["template"]["metadata"]["labels"]
                pod = job["spec"]["template"]["spec"]
                term = pod["affinity"]["podAntiAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"][0]
                assert term["topologyKey"] == "kubernetes.io/hostname"
                assert term["labelSelector"] == {"matchLabels": labels}
                assert labels["app.kubernetes.io/instance"] == release
                assert labels["witful.io/job-revision"] == "1"
                spread = pod["topologySpreadConstraints"][0]
                assert spread["labelSelector"] == {"matchLabels": labels}
                assert spread["whenUnsatisfiable"] == "ScheduleAnyway"

    def test_worker_overrides_reach_the_workload(self) -> None:
        """
        Exercise the configurable lifecycle, placement, security and Secret projections together.

        Returns:
            None: Operator values are preserved in the rendered Job and pod.
        """
        affinity = {
            "nodeAffinity": {
                "preferredDuringSchedulingIgnoredDuringExecution": [
                    {
                        "weight": 50,
                        "preference": {"matchExpressions": [{"key": "pool", "operator": "In", "values": ["batch"]}]},
                    }
                ]
            }
        }
        spread = [
            {
                "maxSkew": 2,
                "topologyKey": "topology.kubernetes.io/zone",
                "whenUnsatisfiable": "DoNotSchedule",
                "labelSelector": {"matchLabels": {"team": "platform"}},
            }
        ]
        tolerations = [{"key": "batch", "operator": "Exists", "effect": "NoSchedule"}]
        values: dict[str, object] = {
            "source": {"existingSecret": "journal", "journalKey": "reviewed.jsonl"},
            "database": {
                "existingSecret": "endpoint",
                "urlKey": "connection",
                "namespace": "team-one",
                "caSecret": "ca",
                "caKey": "certificate.pem",
            },
            "job": {
                "suspend": True,
                "backoffLimit": 4,
                "activeDeadlineSeconds": 720,
                "ttlSecondsAfterFinished": 42,
                "terminationGracePeriodSeconds": 45,
            },
            "scheduling": {
                "nodeSelector": {"pool": "batch"},
                "tolerations": tolerations,
                "priorityClassName": "batch",
                "schedulerName": "custom",
                "affinity": affinity,
                "topologySpreadConstraints": spread,
            },
            "podLabels": {"team": "platform"},
            "podAnnotations": {"example.org/policy": "reviewed"},
            "resources": {"requests": {"cpu": "250m", "memory": "256Mi"}, "limits": {"cpu": "2", "memory": "1Gi"}},
            "podSecurityContext": {"runAsUser": 20001, "runAsGroup": 20001, "fsGroup": 20001},
            "containerSecurityContext": {"readOnlyRootFilesystem": False},
        }
        result = render({"sync": values})
        assert result.returncode == 0, result.stderr
        job = yaml.safe_load(result.stdout)
        spec = job["spec"]
        assert spec["suspend"] is True
        assert [spec[key] for key in ("backoffLimit", "activeDeadlineSeconds", "ttlSecondsAfterFinished")] == [4, 720, 42]
        metadata = spec["template"]["metadata"]
        assert metadata["labels"]["team"] == "platform"
        assert metadata["annotations"] == values["podAnnotations"]
        pod = spec["template"]["spec"]
        assert pod["terminationGracePeriodSeconds"] == 45
        assert pod["affinity"] == affinity
        assert pod["topologySpreadConstraints"] == spread
        assert pod["nodeSelector"] == {"pool": "batch"}
        assert pod["tolerations"] == tolerations
        assert (pod["priorityClassName"], pod["schedulerName"]) == ("batch", "custom")
        assert pod["securityContext"]["runAsUser"] == 20001
        worker = pod["containers"][0]
        assert worker["resources"] == values["resources"]
        assert worker["securityContext"]["readOnlyRootFilesystem"] is False
        assert worker["env"][0]["valueFrom"]["secretKeyRef"] == {"name": "endpoint", "key": "connection"}
        assert worker["env"][1]["value"] == "team-one"
        assert pod["volumes"][0]["secret"]["items"] == [{"key": "reviewed.jsonl", "path": "lessons.jsonl"}]
        assert pod["volumes"][1]["secret"]["items"] == [{"key": "certificate.pem", "path": "root.crt"}]

    def test_soft_placement_and_default_opt_out(self) -> None:
        """
        Preserve schedulability by default and distinguish preferred from required placement.

        Returns:
            None: Default pods have no placement restrictions and the soft preset is a preference.
        """
        default = render({})
        assert default.returncode == 0, default.stderr
        pod = yaml.safe_load(default.stdout)["spec"]["template"]["spec"]
        assert "affinity" not in pod and "topologySpreadConstraints" not in pod
        result = render({"sync": {"scheduling": {"podAntiAffinityPreset": "soft", "topologyKey": "topology.kubernetes.io/zone"}}})
        assert result.returncode == 0, result.stderr
        pod = yaml.safe_load(result.stdout)["spec"]["template"]["spec"]
        preference = pod["affinity"]["podAntiAffinity"]["preferredDuringSchedulingIgnoredDuringExecution"][0]
        assert preference["weight"] == 100
        assert preference["podAffinityTerm"]["topologyKey"] == "topology.kubernetes.io/zone"

    def test_retired_root_controls_are_rejected(self) -> None:
        """
        Reject old root overrides instead of accepting settings that no workload consumes.

        Returns:
            None: Every former synchronization root field has an explicit schema failure.
        """
        values = yaml.safe_load((_CHART / "values.yaml").read_text())
        for name, value in values["sync"].items():
            with self.subTest(path=name):
                result = render({name: value})
                assert result.returncode != 0
                assert name in result.stderr and "additional propert" in result.stderr.lower()

    def test_native_database_overrides_reach_operator(self) -> None:
        """
        Preserve storage, placement, bootstrap, resources and shutdown settings in the Cluster.

        Returns:
            None: Native fields reach the CR without a hand-maintained mapping.
        """
        overrides = {
            "instances": 5,
            "bootstrap": {"initdb": {"database": "records", "owner": "indexer", "secret": {"name": "indexer-auth"}}},
            "storage": {"size": "4Gi", "storageClass": "fast"},
            "affinity": {"nodeSelector": {"pool": "data"}, "podAntiAffinityType": "required"},
            "resources": {"requests": {"cpu": "250m", "memory": "256Mi"}},
            "smartShutdownTimeout": 15,
            "stopDelay": 120,
            "postgresql": {"parameters": {"max_connections": "200"}},
        }
        result = render({"postgresql": {"enabled": True, "spec": overrides}})
        assert result.returncode == 0, result.stderr
        resources = [item for item in yaml.safe_load_all(result.stdout) if item is not None]
        assert {item["kind"] for item in resources} == {"Cluster", "Job"}
        cluster = next(item for item in resources if item["kind"] == "Cluster")
        assert cluster["apiVersion"] == "postgresql.cnpg.io/v1"
        assert cluster["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep"
        spec = cluster["spec"]
        assert spec["instances"] == 5
        assert spec["bootstrap"] == overrides["bootstrap"]
        assert spec["storage"] == overrides["storage"]
        assert spec["affinity"]["nodeSelector"] == {"pool": "data"}
        assert spec["affinity"]["podAntiAffinityType"] == "required"
        assert spec["resources"]["requests"] == {"cpu": "250m", "memory": "256Mi"}
        assert spec["smartShutdownTimeout"] == 15
        assert spec["stopDelay"] == 120
        assert spec["postgresql"] == overrides["postgresql"]

    def test_operator_dependency_is_opt_in_and_allows_native_overrides(self) -> None:
        """
        Render the operator bootstrap phase without creating a database prematurely.

        Returns:
            None: The optional controller, CRDs and suspended worker respect supplied configuration.
        """
        result = render({"cloudnative-pg": {"enabled": True, "replicaCount": 2}, "sync": {"job": {"suspend": True}}})
        assert result.returncode == 0, result.stderr
        resources = [item for item in yaml.safe_load_all(result.stdout) if item is not None]
        assert not any(item["kind"] in {"Cluster", "StatefulSet"} for item in resources)
        controller = next(item for item in resources if item["kind"] == "Deployment")
        assert controller["metadata"]["name"] == "witful-cloudnative-pg"
        assert controller["spec"]["replicas"] == 2
        assert any(item["metadata"]["name"] == "clusters.postgresql.cnpg.io" for item in resources)
        assert next(item for item in resources if item["kind"] == "Job")["spec"]["suspend"] is True

    def test_generated_spec_matches_rendered_operator_crd(self) -> None:
        """
        Compare every upstream spec constraint with the schema consumed by Helm.

        Returns:
            None: The complete generated spec matches the independently rendered dependency CRD.
        """
        result = render({"cloudnative-pg": {"enabled": True}})
        assert result.returncode == 0, result.stderr
        crd = next(
            item
            for item in yaml.safe_load_all(result.stdout)
            if item is not None and item["metadata"]["name"] == "clusters.postgresql.cnpg.io"
        )
        version = next(item for item in crd["spec"]["versions"] if item["name"] == "v1" and item["served"])
        native = version["schema"]["openAPIV3Schema"]["properties"]["spec"]
        schema = json.loads((_CHART / "values.schema.json").read_text())
        generated = schema["properties"]["postgresql"]["properties"]["spec"]
        for key, value in native.items():
            with self.subTest(keyword=key):
                assert generated[key] == value
        Draft7Validator.check_schema(schema)
        Draft7Validator(schema).validate(yaml.safe_load((_CHART / "values.yaml").read_text()))

    def test_database_instance_counts_and_references(self) -> None:
        """
        Support positive instance counts without a local ceiling and render each reviewed reference.

        Returns:
            None: Cluster counts and required placement survive Helm merging.
        """
        for count in (1, 17, 100):
            with self.subTest(instances=count):
                result = render({"postgresql": {"enabled": True, "spec": {"instances": count}}})
                assert result.returncode == 0, result.stderr
                cluster = next(item for item in yaml.safe_load_all(result.stdout) if item["kind"] == "Cluster")
                assert cluster["spec"]["instances"] == count
        for reference, count in (("local", 1), ("postgresql", 3)):
            with self.subTest(reference=reference):
                result = render(yaml.safe_load((_CHART / f"references/{reference}/values.yaml").read_text()))
                assert result.returncode == 0, result.stderr
                resources = [item for item in yaml.safe_load_all(result.stdout) if item is not None]
                assert {item["kind"] for item in resources} == {"Cluster", "Job"}
                cluster = next(item for item in resources if item["kind"] == "Cluster")
                assert cluster["spec"]["instances"] == count
                if reference == "postgresql":
                    assert cluster["spec"]["affinity"]["podAntiAffinityType"] == "required"

    def test_invalid_or_conflicting_inputs_fail_before_deployment(self) -> None:
        """
        Reject malformed native controls, misspelled inputs and ambiguous scheduling ownership.

        Returns:
            None: Every invalid values fixture is rejected by Helm.
        """
        fixtures: list[dict[str, object]] = [
            {"sync": {"scheduling": {"podAntiAffinityPreset": "required"}}},
            {"sync": {"scheduling": {"nodeSelector": {"pool": 2}}}},
            {"sync": {"scheduling": {"tolerations": ["invalid"]}}},
            {"sync": {"scheduling": {"topologySpreadConstraints": [{"maxSkew": 0}]}}},
            {"sync": {"scheduling": {"podAntiAffinityPreset": "hard", "affinity": {"nodeAffinity": {}}}}},
            {"sync": {"podLabels": {"app.kubernetes.io/instance": "another-release"}}},
            {"sync": {"job": {"activeDeadlineSeconds": 0}}},
            {"sync": {"job": {"backoffLimit": 1.5}}},
            {"sync": {"job": {"terminationGracePeriodSeconds": -1}}},
            {"sync": {"database": {"namespace": "bad namespace"}}},
            {"sync": {"source": {"journalKey": ""}}},
            {"postgresql": {"readinessProbe": {"timeoutSeconds": 0}}},
            {"postgresql": {"readinessProbe": {"exec": {"command": ["true"]}}}},
            {"postgresql": {"replicas": 3}},
            {"postgresql": {"spec": {"affinity": {"enablePodAntiAffinity": "always"}}}},
            {"postgresql": {"spec": {"storage": {"size": 4}}}},
            {"scheduler": {"nodeSelector": {}}},
        ]
        # The operator schema requires a positive integer, independently of worker count.
        for value in (0, -1, 1.5, True, "many"):
            fixtures.append({"postgresql": {"spec": {"instances": value}}})

        for values in fixtures:
            with self.subTest(values=values):
                assert render(values).returncode != 0


if __name__ == "__main__":
    unittest.main()
