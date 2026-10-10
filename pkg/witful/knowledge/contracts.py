"""
Generate source schemas from attrs types and validate before cattrs conversion.
"""

from __future__ import annotations

import json
from types import UnionType
from typing import Literal, TypeVar, Union, get_args, get_origin, get_type_hints

from attrs import NOTHING, fields, has
from cattrs import Converter
from jsonschema import Draft202012Validator

from witful.knowledge.models import Annotation, Catalog

__all__ = ["as_data", "schema", "structure"]

T = TypeVar("T")
_CONVERTER = Converter(forbid_extra_keys=True)


def schema(model: object) -> dict[str, object]:
    """
    Derive a closed JSON Schema for the source types used by this package.

    Args:
        model (object): Attrs class, scalar, literal, optional, or homogeneous tuple annotation.

    Returns:
        dict[str, object]: Draft 2020-12 compatible schema with unknown fields rejected.

    Raises:
        TypeError: An unsupported source annotation was introduced without a schema rule.
    """
    primitive = {str: "string", int: "integer", float: "number", bool: "boolean", type(None): "null"}

    if model in primitive:
        return {"type": primitive[model]}

    origin = get_origin(model)
    arguments = get_args(model)

    if origin is Literal:
        return {"enum": list(arguments), "type": "integer" if type(arguments[0]) is int else "string"}
    if origin in (Union, UnionType):
        return {"anyOf": [schema(item) for item in arguments]}
    if origin is tuple and len(arguments) == 2 and arguments[1] is Ellipsis:
        return {"type": "array", "items": schema(arguments[0])}
    if isinstance(model, type) and has(model):
        hints = get_type_hints(model)
        properties = {item.name: schema(hints[item.name]) for item in fields(model)}
        result: dict[str, object] = {
            "type": "object",
            "title": model.__name__,
            "additionalProperties": False,
            "properties": properties,
            "required": [item.name for item in fields(model) if item.default is NOTHING],
        }

        if model is Catalog:
            # Historical snapshots retain their version-1 vocabulary and content hashes.
            legacy_annotation = schema(Annotation)
            legacy_fields = legacy_annotation["properties"]
            assert isinstance(legacy_fields, dict)
            legacy_fields["lemmas"] = legacy_fields.pop("insights")
            legacy = {
                **result,
                "properties": {
                    **properties,
                    "version": {"type": "integer", "const": 1},
                    "annotations": {"type": "array", "items": legacy_annotation},
                },
            }
            current = {**result, "properties": {**properties, "version": {"type": "integer", "const": 2}}}
            return {"title": "Catalog", "anyOf": [current, legacy]}

        return result

    raise TypeError(f"No schema rule for {model}")


def structure(value: object, model: type[T]) -> T:
    """
    Reject coercible but invalid JSON before constructing typed source objects.

    Args:
        value (object): Parsed JSON data at the source boundary.
        model (type[T]): Attrs source type.

    Returns:
        T: Strictly structured immutable value.

    Raises:
        ValidationError: Types, required fields, literals, or unknown fields violate the generated schema.
    """
    Draft202012Validator(schema(model)).validate(value)
    return _CONVERTER.structure(value, model)


def as_data(value: object) -> dict[str, object]:
    """
    Convert a typed root into portable JSON objects and arrays.

    Args:
        value (object): Attrs root model.

    Returns:
        dict[str, object]: JSON-compatible representation suitable for deterministic serialization.

    Raises:
        TypeError: The root does not serialize to a JSON object.
    """
    result: object = json.loads(json.dumps(_CONVERTER.unstructure(value)))

    if not isinstance(result, dict) or not all(isinstance(key, str) for key in result):
        raise TypeError("Expected an object root")

    return dict(result)


def _catalog_spelling(value: object, old: str, new: str) -> dict[str, object]:
    """
    Translate catalog annotation keys without mutating source records or their IDs.

    Args:
        value (object): Validated catalog JSON or its unstructured equivalent.
        old (str): Annotation field spelling present in the input format.
        new (str): Annotation field spelling required by the target format.

    Returns:
        dict[str, object]: Shallow catalog copy with independently copied annotation objects.

    Raises:
        TypeError: The input is not a catalog-shaped JSON object.
    """
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError("Expected a catalog object")

    result: dict[str, object] = dict(value)
    annotations = result.get("annotations", [])

    if not isinstance(annotations, list):
        raise TypeError("Expected catalog annotations to be an array")

    renamed: list[dict[str, object]] = []

    for annotation in annotations:
        if not isinstance(annotation, dict):
            raise TypeError("Expected a catalog annotation object")

        fields_copy: dict[str, object] = dict(annotation)

        if old in fields_copy:
            fields_copy[new] = fields_copy.pop(old)

        renamed.append(fields_copy)

    result["annotations"] = renamed
    return result


def _structure_catalog(value: object, model: type[Catalog]) -> Catalog:
    """
    Read either catalog vocabulary while preserving its original format version.

    Args:
        value (object): Catalog JSON already validated against the versioned schema.
        model (type[Catalog]): Target catalog class supplied by cattrs.

    Returns:
        Catalog: Current Python attributes with the source version retained for serialization.
    """
    normalized = _catalog_spelling(value, "lemmas", "insights")

    # Versionless sources predate explicit migration; canonical version 2 is preferred when valid.
    if "version" not in normalized:
        current_schema = schema(Catalog)["anyOf"]
        assert isinstance(current_schema, list)
        normalized["version"] = 2 if Draft202012Validator(current_schema[0]).is_valid(value) else 1

    return _CONVERTER.structure_attrs_fromdict(normalized, model)


def _unstructure_catalog(value: Catalog) -> dict[str, object]:
    """
    Retain legacy snapshot bytes and emit the canonical spelling for new catalogs.

    Args:
        value (Catalog): Catalog whose version selects its serialized field spelling.

    Returns:
        dict[str, object]: Versioned portable catalog data with stable historical identifiers.
    """
    result: object = json.loads(json.dumps(_CONVERTER.unstructure_attrs_asdict(value)))
    old, new = ("insights", "lemmas") if value.version == 1 else ("insights", "insights")
    return _catalog_spelling(result, old, new)


_CONVERTER.register_structure_hook(Catalog, _structure_catalog)
_CONVERTER.register_unstructure_hook(Catalog, _unstructure_catalog)
