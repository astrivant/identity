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
        result = render(values)
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
        result = render({"scheduling": {"podAntiAffinityPreset": "soft", "topologyKey": "topology.kubernetes.io/zone"}})
        assert result.returncode == 0, result.stderr
        pod = yaml.safe_load(result.stdout)["spec"]["template"]["spec"]
        preference = pod["affinity"]["podAntiAffinity"]["preferredDuringSchedulingIgnoredDuringExecution"][0]
        assert preference["weight"] == 100
        assert preference["podAffinityTerm"]["topologyKey"] == "topology.kubernetes.io/zone"

    def test_development_database_overrides(self) -> None:
        """
        Keep single-node storage and connection settings aligned with operator inputs.

        Returns:
            None: Database settings reach the container, readiness command and volume claim.
        """
        values: dict[str, object] = {
            "postgresql": {
                "enabled": True,
                "username": "indexer",
                "database": "records",
                "passwordKey": "credential",
                "storageSize": "4Gi",
                "storageClass": "fast",
                "nodeSelector": {"pool": "data"},
                "resources": {"requests": {"cpu": "250m", "memory": "256Mi"}},
                "readinessProbe": {"timeoutSeconds": 4},
                "terminationGracePeriodSeconds": 60,
            }
        }
        result = render(values)
        assert result.returncode == 0, result.stderr
        stateful = next(item for item in yaml.safe_load_all(result.stdout) if item["kind"] == "StatefulSet")
        assert stateful["spec"]["replicas"] == 1
        pod = stateful["spec"]["template"]["spec"]
        assert pod["nodeSelector"] == {"pool": "data"}
        assert pod["terminationGracePeriodSeconds"] == 60
        database = pod["containers"][0]
        assert [item.get("value") for item in database["env"][:2]] == ["records", "indexer"]
        assert database["env"][2]["valueFrom"]["secretKeyRef"]["key"] == "credential"
        assert database["readinessProbe"]["exec"]["command"] == ["pg_isready", "-U", "indexer", "-d", "records"]
        assert database["readinessProbe"]["timeoutSeconds"] == 4
        assert database["resources"]["requests"] == {"cpu": "250m", "memory": "256Mi"}
        claim = stateful["spec"]["volumeClaimTemplates"][0]["spec"]
        assert claim["storageClassName"] == "fast"
        assert claim["resources"]["requests"]["storage"] == "4Gi"

    def test_invalid_or_conflicting_inputs_fail_before_deployment(self) -> None:
        """
        Reject malformed native controls, misspelled inputs and ambiguous scheduling ownership.

        Returns:
            None: Every invalid values fixture is rejected by Helm.
        """
        fixtures: list[dict[str, object]] = [
            {"scheduling": {"podAntiAffinityPreset": "required"}},
            {"scheduling": {"nodeSelector": {"pool": 2}}},
            {"scheduling": {"tolerations": ["invalid"]}},
            {"scheduling": {"topologySpreadConstraints": [{"maxSkew": 0}]}},
            {"scheduling": {"podAntiAffinityPreset": "hard", "affinity": {"nodeAffinity": {}}}},
            {"podLabels": {"app.kubernetes.io/instance": "another-release"}},
            {"job": {"activeDeadlineSeconds": 0}},
            {"job": {"backoffLimit": 1.5}},
            {"job": {"terminationGracePeriodSeconds": -1}},
            {"database": {"namespace": "bad namespace"}},
            {"source": {"journalKey": ""}},
            {"postgresql": {"readinessProbe": {"timeoutSeconds": 0}}},
            {"postgresql": {"readinessProbe": {"exec": {"command": ["true"]}}}},
            {"postgresql": {"replicas": 3}},
            {"scheduler": {"nodeSelector": {}}},
        ]
        for values in fixtures:
            with self.subTest(values=values):
                assert render(values).returncode != 0


if __name__ == "__main__":
    unittest.main()
