"""
Build schema-validated synthetic responses from refreshable vendor examples.
"""

from __future__ import annotations

import copy
import json

from openapi_schema_validator import OAS30ReadValidator
from provider_contracts.refresh import DATA
from witful.delivery.providers.base import object_value


def resolved(document: dict[str, object], value: object) -> dict[str, object]:
    """
    Resolve a response or example reference within the pinned snapshot.

    Args:
        document (dict[str, object]): Complete snapshot reference root.
        value (object): Inline mapping or local reference.

    Returns:
        dict[str, object]: Referenced mapping.
    """
    row = object_value(value)
    if "$ref" in row:
        target: object = document
        for part in str(row["$ref"]).split("/")[1:]:
            target = object_value(target)[part]
        return object_value(target)
    return row


def overlay(example: object, fixture: object) -> object:
    """
    Supply required example fields while retaining deliberate synthetic scenario values.

    Args:
        example (object): Vendor example, used only as structural scaffolding.
        fixture (object): Synthetic coherent project/PR fixture.

    Returns:
        object: New response value without changing either input.
    """
    if isinstance(example, dict) and isinstance(fixture, dict):
        return {**copy.deepcopy(example), **{key: overlay(example.get(key), value) for key, value in fixture.items()}}
    if isinstance(example, list) and isinstance(fixture, list) and example:
        return [overlay(example[0], item) for item in fixture]
    return copy.deepcopy(fixture)


def response_body(provider: str, operation: str, fixture: object) -> object:
    """
    Validate every success payload before the mock server serves it to an SDK.

    Args:
        provider (str): Pinned vendor snapshot name.
        operation (str): Reviewed operation selection.
        fixture (object): Coherent synthetic response overrides.

    Returns:
        object: Response conforming to the selected vendor schema.
    """
    document = object_value(json.loads((DATA / f"{provider}.json").read_text()))
    response = resolved(document, object_value(document["responses"])[operation])
    media = object_value(object_value(response["content"])["application/json"])
    examples = object_value(media.get("examples", {}))
    example = resolved(document, next(iter(examples.values()))).get("value") if examples else None
    value = overlay(example, fixture)
    # OpenAPI 3.0 nullable/readOnly semantics require its response validator, not plain JSON Schema.
    schema = {**object_value(media["schema"]), "components": document["components"]}
    OAS30ReadValidator.check_schema(schema)
    errors = list(OAS30ReadValidator(schema).iter_errors(value))
    assert not errors, [(list(error.path), error.message) for error in errors]
    return value
