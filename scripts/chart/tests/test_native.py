"""
Verify opt-in native controller deployment, generated configuration validation and single-writer refusals.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml
from jsonschema import ValidationError, validate

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "helm/witful"
_REFERENCE = _CHART / "references/native/values.yaml"


def render(*overrides: str) -> list[dict[str, object]]:
    """
    Render the complete reference with explicit test overrides and no cluster interaction.

    Args:
        *overrides (str): Native Helm command-line options.

    Returns:
        list[dict[str, object]]: Actual parsed Kubernetes resources.
    """
    result = subprocess.run(
        ["helm", "template", "native", str(_CHART), "-f", str(_REFERENCE), *overrides],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return list(yaml.safe_load_all(result.stdout))


def test_native_controller_has_private_ha_and_runtime_controls() -> None:
    """
    Render independently scalable PostgreSQL workers with explicit secrets, memory storage and private operational admission.

    Returns:
        None: The default sync job is absent only for the explicit native profile.
    """
    documents = render(
        "--set",
        "controller.replicas=3,controller.configuration.runtime.workers=24,controller.configuration.runtime.port=9443,"
        "controller.configuration.runtime.recovery_admission=3",
    )
    resources = {value["kind"]: value for value in documents}
    assert "Job" not in resources and "StatefulSet" not in resources
    deployment = resources["Deployment"]
    spec = deployment["spec"]
    assert isinstance(spec, dict) and spec["replicas"] == 3
    pod = spec["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    container = pod["containers"][0]
    assert container["args"] == ["native", "controller", "serve", "--config", "/etc/witful/settings.json"]
    assert container["ports"] == [{"name": "tls", "containerPort": 9443}]
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert all("secretKeyRef" in item["valueFrom"] for item in container["env"] if item["name"].endswith("DATABASE_URL"))
    volumes = {item["name"]: item for item in pod["volumes"]}
    assert volumes["working"]["emptyDir"]["medium"] == "Memory"
    assert "source" not in volumes
    assert container["livenessProbe"]["tcpSocket"] == {"port": "tls"}
    assert "health" in container["readinessProbe"]["exec"]["command"]
    assert "PodDisruptionBudget" in resources and "NetworkPolicy" in resources
    configuration = resources["ConfigMap"]["data"]
    assert isinstance(configuration, dict)
    settings = json.loads(configuration["settings.json"])
    assert settings["runtime"]["workers"] == 24
    assert settings["runtime"]["recovery_admission"] == 3
    assert "DATABASE_URL" not in json.dumps(settings)


def test_native_schema_rejects_unknown_config_and_inline_credentials() -> None:
    """
    Reject unsupported runtime inputs and secret contents before rendering a ConfigMap.

    Returns:
        None: The generated chart schema follows the closed typed controller contract.
    """
    schema = json.loads((_CHART / "values.schema.json").read_text())
    baseline = yaml.safe_load((_CHART / "values.yaml").read_text())
    reference = yaml.safe_load(_REFERENCE.read_text())
    baseline["controller"]["enabled"] = True
    baseline["controller"]["configuration"] = reference["controller"]["configuration"]
    validate(baseline, schema)
    baseline["controller"]["configuration"]["runtime"]["workerz"] = 9
    with pytest.raises(ValidationError):
        validate(baseline, schema)
    del baseline["controller"]["configuration"]["runtime"]["workerz"]
    baseline["controller"]["configuration"]["broker"]["private_key"] = "synthetic-denied-key-material"
    with pytest.raises(ValidationError):
        validate(baseline, schema)


def test_controller_pod_controls_are_independent_of_sync() -> None:
    """
    Preserve controller-specific deployment choices without inheriting the inactive Job's overrides.

    Returns:
        None: Controller image, resources, placement, labels and security come from its own namespace.
    """
    documents = render(
        "--set",
        "controller.image.repository=registry.example/controller,controller.image.tag=reviewed,"
        "controller.image.pullPolicy=Always,controller.imagePullSecrets[0]=controller-registry,"
        "controller.resources.requests.cpu=275m,controller.scheduling.nodeSelector.pool=native,"
        "controller.podLabels.team=platform,controller.podAnnotations.review=accepted,"
        "controller.podSecurityContext.runAsUser=20001,controller.containerSecurityContext.runAsGroup=20001,"
        "sync.image.repository=registry.example/sync,sync.image.tag=other,"
        "sync.resources.requests.cpu=900m,sync.scheduling.nodeSelector.pool=batch,sync.podLabels.team=batch",
    )
    deployment = next(item for item in documents if item["kind"] == "Deployment")
    specification = deployment["spec"]
    assert isinstance(specification, dict)
    pod = specification["template"]
    assert pod["metadata"]["labels"]["team"] == "platform"
    assert pod["metadata"]["annotations"]["review"] == "accepted"
    assert pod["spec"]["nodeSelector"] == {"pool": "native"}
    assert pod["spec"]["imagePullSecrets"] == [{"name": "controller-registry"}]
    assert pod["spec"]["securityContext"]["runAsUser"] == 20001
    container = pod["spec"]["containers"][0]
    assert container["image"] == "registry.example/controller:reviewed"
    assert container["imagePullPolicy"] == "Always"
    assert container["resources"]["requests"]["cpu"] == "275m"
    assert container["securityContext"]["runAsGroup"] == 20001


@pytest.mark.parametrize(
    "override",
    (
        "controller.configuration.backend.kind=git",
        "controller.terminationGracePeriodSeconds=30",
        "controller.pdb.minAvailable=2",
        "controller.secretEnvironment.TMPDIR.name=unsafe,controller.secretEnvironment.TMPDIR.key=value",
        "controller.scheduling.podAntiAffinityPreset=hard,controller.scheduling.affinity.nodeAffinity={}",
        "controller.podLabels.app\\.kubernetes\\.io/instance=another-release",
    ),
)
def test_native_chart_refuses_unsafe_ownership(override: str) -> None:
    """
    Fail explicitly when configuration would violate writer ownership or the graceful termination budget.

    Args:
        override (str): Individually invalid deployment control.

    Returns:
        None: Helm refuses the deployment before any cluster mutation.
    """
    with pytest.raises(subprocess.CalledProcessError):
        render("--set", override)


def test_native_git_requires_one_writer_and_retains_existing_volume() -> None:
    """
    Use a Recreate deployment and existing protected volume for the explicit local Git alternative.

    Returns:
        None: The chart never creates or deletes a database-like StatefulSet or new claim for this profile.
    """
    documents = render(
        "--set",
        "controller.replicas=1,controller.configuration.runtime.workers=1,controller.pdb.minAvailable=0,"
        "controller.configuration.backend.kind=git,controller.configuration.backend.path=/var/lib/witful/git,"
        "controller.git.existingClaim=reviewed-git",
    )
    deployment = next(item for item in documents if item["kind"] == "Deployment")
    spec = deployment["spec"]
    assert isinstance(spec, dict) and spec["strategy"] == {"type": "Recreate"}
    assert not any(item["kind"] == "PersistentVolumeClaim" for item in documents)
    assert {"name": "git", "persistentVolumeClaim": {"claimName": "reviewed-git"}} in spec["template"]["spec"]["volumes"]


def test_projection_gateway_has_independent_single_writer_credentials() -> None:
    """
    Render the isolated gateway reference and reject replicas or source-database credentials that violate its privilege boundary.

    Returns:
        None: Gateway storage ownership, credentials and current complete configuration are reflected in actual Kubernetes output.
    """
    reference = _CHART / "references/projection/values.yaml"
    result = subprocess.run(
        ["helm", "template", "gateway", str(_CHART), "-f", str(reference)], capture_output=True, text=True, check=True, timeout=30
    )
    resources = {value["kind"]: value for value in yaml.safe_load_all(result.stdout)}
    deployment = resources["Deployment"]["spec"]
    assert deployment["replicas"] == 1 and deployment["strategy"] == {"type": "Recreate"}
    pod = deployment["template"]["spec"]
    assert {item["name"] for item in pod["volumes"]}.isdisjoint({"git", "source", "database"})
    environment = {item["name"] for item in pod["containers"][0]["env"]}
    assert "WITFUL_AUTHORITY_DATABASE_URL" in environment and "WITFUL_DATABASE_URL" not in environment
    assert resources["NetworkPolicy"]["spec"]["egress"] == []
    for override in (
        "controller.replicas=2",
        "controller.configuration.runtime.workers=2",
        "controller.secretEnvironment.WITFUL_DATABASE_URL.name=unapproved,controller.secretEnvironment.WITFUL_DATABASE_URL.key=url",
    ):
        rejected = subprocess.run(
            ["helm", "template", "gateway", str(_CHART), "-f", str(reference), "--set", override],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert rejected.returncode != 0


def test_projection_scheduler_uses_one_network_policy_and_distinct_scoped_clients() -> None:
    """
    Render two client scheduling jobs without duplicating shared policy or inheriting controller database/broker credentials.

    Returns:
        None: Each bounded cycle owns its service account and client mount, with one shared deny-by-default network policy.
    """
    clients = json.dumps([{"name": name, "secretName": name + "-client", "key": "client.json"} for name in ("one", "two")])
    resources = render(
        "--set",
        "controller.scheduler.enabled=true,controller.image.repository=registry.example/controller,"
        "controller.image.tag=reviewed,sync.image.repository=registry.example/sync,sync.image.tag=other",
        "--set-json",
        f"controller.scheduler.clients={clients}",
    )
    jobs = [item for item in resources if item["kind"] == "CronJob"]
    policies: list[dict[str, object]] = []
    for item in resources:
        metadata = item["metadata"]
        assert isinstance(metadata, dict)
        if item["kind"] == "NetworkPolicy" and metadata["name"].endswith("-delivery"):
            policies.append(item)
    assert len(jobs) == 2 and len(policies) == 1
    policy = policies[0]["spec"]
    assert isinstance(policy, dict) and policy["egress"] == [] and policy["ingress"] == []
    for job in jobs:
        schedule = job["spec"]
        assert isinstance(schedule, dict) and schedule["concurrencyPolicy"] == "Forbid"
        spec = schedule["jobTemplate"]["spec"]
        assert spec["backoffLimit"] == 0 and spec["activeDeadlineSeconds"] > 300
        pod = spec["template"]["spec"]
        assert pod["automountServiceAccountToken"] is False
        container = pod["containers"][0]
        assert container["image"] == "registry.example/controller:reviewed"
        assert container["args"][:3] == ["native", "projection", "tick"]
        assert all("valueFrom" not in item for item in container["env"])
        assert {item["name"] for item in pod["volumes"]} == {"client", "working"}
