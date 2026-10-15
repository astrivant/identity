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
        "--set", "controller.replicas=3,controller.configuration.runtime.workers=24,controller.configuration.runtime.port=9443"
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


@pytest.mark.parametrize(
    "override",
    (
        "controller.configuration.backend.kind=git",
        "controller.terminationGracePeriodSeconds=30",
        "controller.pdb.minAvailable=2",
        "controller.secretEnvironment.TMPDIR.name=unsafe,controller.secretEnvironment.TMPDIR.key=value",
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
