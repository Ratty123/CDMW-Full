"""Checks tool arguments against the tool's JSON schema, before anything runs.

A small subset of JSON Schema is enough for the tool table and keeps the
check in the standard library: ``type`` (one or a list), ``properties``,
``required``, ``additionalProperties`` (true or false), ``enum``,
``minimum``/``maximum``, ``minLength``/``maxLength``, ``items``,
``minItems``/``maxItems`` and ``default`` for top-level properties.
"""

from __future__ import annotations

from collections.abc import Mapping

from cdmw.mcp.errors import INVALID_ARGUMENTS, ToolError

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}
_KNOWN_KEYS = frozenset({
    "type", "properties", "required", "additionalProperties", "enum", "minimum", "maximum", "minLength",
    "maxLength", "items", "minItems", "maxItems", "default", "description", "title",
})


def check_schema_shape(schema: Mapping[str, object], where: str = "schema") -> None:
    """Raise ValueError when a schema uses something this checker does not enforce."""

    unknown = set(schema) - _KNOWN_KEYS
    if unknown:
        raise ValueError(f"{where} uses unsupported keywords: {sorted(unknown)}")
    types = schema.get("type")
    for name in types if isinstance(types, list) else [types] if types else []:
        if name not in _TYPES:
            raise ValueError(f"{where} has an unknown type {name!r}")
    for key, sub in dict(schema.get("properties") or {}).items():
        check_schema_shape(sub, f"{where}.{key}")
    if isinstance(schema.get("items"), Mapping):
        check_schema_shape(schema["items"], f"{where}[]")


def _check(value: object, schema: Mapping[str, object], where: str) -> None:
    types = schema.get("type")
    if types:
        names = types if isinstance(types, list) else [types]
        if not any(_TYPES[name](value) for name in names):
            raise ToolError(INVALID_ARGUMENTS, f"{where} must be {' or '.join(names)}")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolError(INVALID_ARGUMENTS, f"{where} must be one of {', '.join(map(str, schema['enum']))}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ToolError(INVALID_ARGUMENTS, f"{where} must be at least {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise ToolError(INVALID_ARGUMENTS, f"{where} must be at most {schema['maximum']}")
    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            raise ToolError(INVALID_ARGUMENTS, f"{where} must not be empty" if schema.get("minLength") == 1
                            else f"{where} must have at least {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise ToolError(INVALID_ARGUMENTS, f"{where} must have at most {schema['maxLength']} characters")
    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            raise ToolError(INVALID_ARGUMENTS, f"{where} needs at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ToolError(INVALID_ARGUMENTS, f"{where} takes at most {schema['maxItems']} items")
        if isinstance(schema.get("items"), Mapping):
            for index, item in enumerate(value):
                _check(item, schema["items"], f"{where}[{index}]")
    if isinstance(value, dict):
        properties = dict(schema.get("properties") or {})
        for name in schema.get("required") or ():
            if name not in value:
                raise ToolError(INVALID_ARGUMENTS, f"{where}.{name} is required" if where != "arguments"
                                else f"{name} is required")
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                raise ToolError(INVALID_ARGUMENTS, f"Unknown argument {extra[0]!r}" if where == "arguments"
                                else f"{where} has an unknown field {extra[0]!r}")
        for name, sub in properties.items():
            if name in value:
                _check(value[name], sub, name if where == "arguments" else f"{where}.{name}")


def validate_arguments(arguments: object, schema: Mapping[str, object]) -> dict[str, object]:
    """The arguments, checked, with the schema's top-level defaults filled in."""

    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ToolError(INVALID_ARGUMENTS, "arguments must be an object")
    _check(arguments, schema, "arguments")
    filled = dict(arguments)
    for name, sub in dict(schema.get("properties") or {}).items():
        if name not in filled and "default" in sub:
            filled[name] = sub["default"]
    return filled
