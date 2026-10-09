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
        return {
            "type": "object",
            "title": model.__name__,
            "additionalProperties": False,
            "properties": {item.name: schema(hints[item.name]) for item in fields(model)},
            "required": [item.name for item in fields(model) if item.default is NOTHING],
        }

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
