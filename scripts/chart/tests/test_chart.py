"""
Verify rendered chart and generated Compose contracts without starting infrastructure.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

import yaml
from jsonschema import validate

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "deploy/helm/witful"


class ChartContracts(unittest.TestCase):
    """
    Check worker bounds, secret projection, and local replica configuration.
    """

    def test_worker_mounts_and_privileges(self) -> None:
        """
        Render secret-backed workers with private CA and registry credentials.

        Returns:
            None: The chart preserves the non-root, read-only, and bounded-worker contract.
        """
        result = subprocess.run(
            ["helm", "template", "witful", str(_CHART), "--set", "workers=3,database.caSecret=ca,imagePullSecrets[0]=registry"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        job = yaml.safe_load(result.stdout)
        validate(
            job,
            {
                "type": "object",
                "required": ["spec"],
                "properties": {
                    "spec": {
                        "type": "object",
                        "required": ["parallelism", "completions", "template"],
                        "properties": {
                            "parallelism": {"const": 3},
                            "completions": {"const": 3},
                            "template": {
                                "type": "object",
                                "properties": {
                                    "spec": {
                                        "type": "object",
                                        "properties": {
                                            "automountServiceAccountToken": {"const": False},
                                            "imagePullSecrets": {"const": [{"name": "registry"}]},
                                        },
                                    }
                                },
                            },
                        },
                    },
                },
            },
        )
        pod = job["spec"]["template"]["spec"]
        container = pod["containers"][0]
        assert container["securityContext"]["readOnlyRootFilesystem"] is True
        assert pod["securityContext"]["runAsNonRoot"] is True
        assert container["env"][0]["valueFrom"]["secretKeyRef"] == {"name": "witful-database", "key": "url"}
        assert container["env"][2] == {"name": "PGSSLROOTCERT", "value": "/etc/postgres/root.crt"}
        assert all(mount["readOnly"] for mount in container["volumeMounts"])

    def test_invalid_worker_counts_fail_rendering(self) -> None:
        """
        Reject fractional, negative, zero, or excessive concurrency at the chart boundary.

        Returns:
            None: Invalid configurations fail before a workload is created.
        """
        for value in ("0", "-1", "17", "1.5"):
            with self.subTest(workers=value):
                result = subprocess.run(
                    ["helm", "template", "witful", str(_CHART), "--set", f"workers={value}"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                assert result.returncode != 0

    def test_compose_keeps_secrets_runtime_only_and_allows_scaling(self) -> None:
        """
        Require runtime credentials and permit multiple workers without fixed container names.

        Returns:
            None: The generated runtime mounts only the journal and has database health gating.
        """
        compose = yaml.safe_load((_ROOT / "deploy/compose.yaml").read_text())
        services = compose["services"]
        assert all("container_name" not in item for item in services.values())
        assert services["witful"]["environment"]["WITFUL_DATABASE_URL"].startswith("${WITFUL_DATABASE_URL:?")
        assert services["witful"]["depends_on"]["postgres"]["condition"] == "service_healthy"
        assert services["witful"]["volumes"] == ["../lessons.jsonl:/source/lessons.jsonl:ro"]
        assert services["witful"]["read_only"] is True
        assert "ports" not in services["postgres"]


if __name__ == "__main__":
    unittest.main()
