"""
Add deployment constraints to the Bitnami-generated chart schema.
"""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

import yaml
from witful.knowledge.contracts import schema as model_schema
from witful.native.config import Settings

_CHART = Path(__file__).resolve().parents[2] / "helm/witful"


def main() -> None:
    """
    Preserve generated descriptions and defaults while validating chart-specific choices.

    Returns:
        None: The generated schema is rewritten for Helm validation.
    """
    schema: dict[str, object] = json.loads((_CHART / "values.schema.json").read_text())
    rules: dict[str, dict[str, object]] = {
        "workers": {"type": "integer", "minimum": 1},
        "image.pullPolicy": {"enum": ["Always", "IfNotPresent", "Never"]},
        "imagePullSecrets": {"default": [], "items": {"type": "string", "minLength": 1}},
        "database.namespace": {"pattern": "^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"},
        "scheduling.podAntiAffinityPreset": {"enum": ["", "soft", "hard"]},
        "scheduling.topologySpreadConstraints": {
            "default": [],
            "items": {
                "type": "object",
                "required": ["maxSkew", "topologyKey", "whenUnsatisfiable"],
                "properties": {
                    "maxSkew": {"type": "integer", "minimum": 1},
                    "topologyKey": {"type": "string", "minLength": 1},
                    "whenUnsatisfiable": {"enum": ["DoNotSchedule", "ScheduleAnyway"]},
                    "labelSelector": {"type": "object"},
                },
            },
        },
    }

    rules["controller.replicas"] = {"type": "integer", "minimum": 1}
    rules["controller.terminationGracePeriodSeconds"] = {"type": "integer", "minimum": 1}
    rules["controller.pdb.minAvailable"] = {"type": "integer", "minimum": 0}
    rules["controller.secretEnvironment"] = {
        "type": "object",
        "default": {},
        "propertyNames": {"pattern": "^[A-Z_][A-Z0-9_]*$"},
        "additionalProperties": {
            "type": "object",
            "required": ["name", "key"],
            "additionalProperties": False,
            "properties": {"name": {"type": "string", "minLength": 1}, "key": {"type": "string", "minLength": 1}},
        },
    }
    rules["controller.secretMounts"] = {
        "type": "array",
        "default": [],
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "secretName", "mountPath", "items"],
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "secretName": {"type": "string", "minLength": 1},
                "mountPath": {"type": "string", "pattern": "^/"},
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["key", "path"],
                        "additionalProperties": False,
                        "properties": {"key": {"type": "string", "minLength": 1}, "path": {"type": "string", "minLength": 1}},
                    },
                },
            },
        },
    }
    rules["controller.archiveVolumes"] = {
        "type": "array",
        "default": [],
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "existingClaim", "mountPath", "readOnly"],
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "existingClaim": {"type": "string", "minLength": 1},
                "mountPath": {"type": "string", "pattern": "^/"},
                "readOnly": {"type": "boolean"},
            },
        },
    }
    for path in ("controller.networkPolicy.ingress", "controller.networkPolicy.egress"):
        rules[path] = {"type": "array", "default": [], "items": {"type": "object"}}
    for probe, names in {
        "startup": ("failureThreshold", "periodSeconds"),
        "liveness": ("failureThreshold", "periodSeconds"),
        "readiness": ("failureThreshold", "periodSeconds", "timeoutSeconds"),
    }.items():
        for name in names:
            rules[f"controller.probes.{probe}.{name}"] = {"type": "integer", "minimum": 1}

    # Numeric Kubernetes fields must reject fractions before API admission.
    for path, minimum in {
        "job.backoffLimit": 0,
        "job.activeDeadlineSeconds": 1,
        "job.ttlSecondsAfterFinished": 0,
        "job.terminationGracePeriodSeconds": 1,
    }.items():
        rules[path] = {"type": "integer", "minimum": minimum}

    for path in (
        "image.repository",
        "image.tag",
        "source.existingSecret",
        "source.journalKey",
        "database.existingSecret",
        "database.urlKey",
        "database.caKey",
        "scheduling.topologyKey",
    ):
        rules[path] = {"minLength": 1}

    # Empty arrays have no element type for Bitnami to infer; these contain native objects.
    for path in ("scheduling.tolerations",):
        rules[path] = {"default": [], "items": {"type": "object"}}
    for path in ("podLabels", "podAnnotations", "scheduling.nodeSelector"):
        rules[path] = {"default": {}, "additionalProperties": {"type": "string"}}
    for path in ("scheduling.affinity",):
        rules[path] = {"default": {}}

    rules["containerSecurityContext.capabilities.drop"] = {"default": ["ALL"], "items": {"type": "string"}}
    for path, constraints in rules.items():
        field(schema, path).update(constraints)

    # Generate the complete controller configuration from the runtime model; disabled profiles may keep it empty.
    configuration = model_schema(Settings)
    field(schema, "controller.configuration").clear()
    field(schema, "controller.configuration").update({"anyOf": [{"type": "object", "maxProperties": 0}, configuration]})
    schema["allOf"] = [
        {
            "if": {"properties": {"controller": {"properties": {"enabled": {"const": True}}}}},
            "then": {"properties": {"controller": {"properties": {"configuration": configuration}}}},
        }
    ]

    # Keep the complete native spec in sync with the operator instead of maintaining a parallel model.
    spec = field(cluster_schema(), "spec")
    field(schema, "postgresql.spec").update(spec)
    field(schema, "cloudnative-pg")["additionalProperties"] = True

    # Catch misspelled chart-owned parameters, while native Kubernetes maps stay extensible.
    for path in (
        "",
        "image",
        "source",
        "database",
        "job",
        "scheduling",
        "postgresql",
        "controller",
        "controller.git",
        "controller.pdb",
        "controller.networkPolicy",
        "controller.probes",
        "controller.probes.startup",
        "controller.probes.readiness",
        "controller.probes.liveness",
    ):
        target = field(schema, path)
        properties = target.get("properties")
        if not isinstance(properties, dict):
            raise ValueError(f"Generated chart schema has no properties at {path}")
        target["additionalProperties"] = False
        target["required"] = list(properties)

    (_CHART / "values.schema.json").write_text(json.dumps(schema, indent=4) + "\n")


def cluster_schema() -> dict[str, object]:
    """
    Load the authoritative Cluster admission schema from the locked operator chart.

    Returns:
        dict[str, object]: OpenAPI schema for the served v1 Cluster resource.

    Raises:
        ValueError: The dependency lock, archive or upstream CRD layout is unsupported.
    """
    lock = yaml.safe_load((_CHART / "Chart.lock").read_text())
    dependency = next(item for item in lock["dependencies"] if item["name"] == "cloudnative-pg")
    archive_path = _CHART / "charts" / f"cloudnative-pg-{dependency['version']}.tgz"
    with tarfile.open(archive_path, "r:gz") as archive:
        source = archive.extractfile("cloudnative-pg/templates/crds/crds.yaml")
        if source is None:
            raise ValueError("Locked operator chart has no CRD source")
        raw = source.read().decode()

    # The reviewed upstream file contains static CRDs inside one conditional; fail on a changed template contract.
    prefix, suffix = "{{- if .Values.crds.create }}\n", "{{- end }}\n"
    if not raw.startswith(prefix) or not raw.endswith(suffix):
        raise ValueError("Review the operator CRD template before regenerating its schema")
    payload = raw[len(prefix) : -len(suffix)]
    if "{{" in payload or "}}" in payload:
        raise ValueError("Operator CRDs contain unsupported template expressions")
    for resource in yaml.safe_load_all(payload):
        if resource["metadata"]["name"] == "clusters.postgresql.cnpg.io":
            for version in resource["spec"]["versions"]:
                if version["name"] == "v1" and version["served"]:
                    result: dict[str, object] = version["schema"]["openAPIV3Schema"]
                    return result
    raise ValueError("Locked operator chart has no served v1 Cluster schema")


def field(schema: dict[str, object], path: str) -> dict[str, object]:
    """
    Locate an existing generated field instead of inventing an unimplemented input.

    Args:
        schema (dict[str, object]): Bitnami-generated schema.
        path (str): Dot-separated chart-owned property path; empty selects the root.

    Returns:
        dict[str, object]: Mutable schema for the existing property.

    Raises:
        ValueError: An annotation or generated property is missing.
    """
    current = schema
    for name in path.split(".") if path else ():
        properties = current.get("properties")
        if not isinstance(properties, dict) or not isinstance(properties.get(name), dict):
            raise ValueError(f"Generated chart schema is missing {path}")
        current = properties[name]
    return current


if __name__ == "__main__":
    main()
