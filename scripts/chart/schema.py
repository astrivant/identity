"""
Add deployment constraints to the Bitnami-generated chart schema.
"""

from __future__ import annotations

import json
from pathlib import Path

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

    # Numeric Kubernetes fields must reject fractions before API admission.
    for path, minimum in {
        "job.backoffLimit": 0,
        "job.activeDeadlineSeconds": 1,
        "job.ttlSecondsAfterFinished": 0,
        "job.terminationGracePeriodSeconds": 1,
        "postgresql.terminationGracePeriodSeconds": 1,
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
        "postgresql.image",
        "postgresql.existingSecret",
        "postgresql.passwordKey",
        "postgresql.database",
        "postgresql.username",
        "postgresql.storageSize",
    ):
        rules[path] = {"minLength": 1}

    # Empty arrays have no element type for Bitnami to infer; these contain native objects.
    for path in ("scheduling.tolerations", "postgresql.tolerations"):
        rules[path] = {"default": [], "items": {"type": "object"}}
    for path in ("podLabels", "podAnnotations", "scheduling.nodeSelector", "postgresql.nodeSelector"):
        rules[path] = {"default": {}, "additionalProperties": {"type": "string"}}
    for path in ("scheduling.affinity", "postgresql.affinity"):
        rules[path] = {"default": {}}

    rules["containerSecurityContext.capabilities.drop"] = {"default": ["ALL"], "items": {"type": "string"}}
    rules["postgresql.readinessProbe"] = {"additionalProperties": False}
    for name, minimum in {
        "initialDelaySeconds": 0,
        "periodSeconds": 1,
        "timeoutSeconds": 1,
        "successThreshold": 1,
        "failureThreshold": 1,
    }.items():
        rules[f"postgresql.readinessProbe.{name}"] = {"type": "integer", "minimum": minimum}

    for path, constraints in rules.items():
        field(schema, path).update(constraints)

    # Catch misspelled chart-owned parameters, while native Kubernetes maps stay extensible.
    for path in ("", "image", "source", "database", "job", "scheduling", "postgresql"):
        target = field(schema, path)
        properties = target.get("properties")
        if not isinstance(properties, dict):
            raise ValueError(f"Generated chart schema has no properties at {path}")
        target["additionalProperties"] = False
        target["required"] = list(properties)

    (_CHART / "values.schema.json").write_text(json.dumps(schema, indent=4) + "\n")


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
