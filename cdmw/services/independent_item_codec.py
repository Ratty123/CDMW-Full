"""Closed, data-only codec for the version-one portable authoring recipe."""
from dataclasses import fields, is_dataclass
from enum import Enum
import math
from functools import lru_cache
from collections.abc import Mapping
from types import UnionType
from typing import Union, get_args, get_origin, get_type_hints

from cdmw.domain.new_item import authoring, spec, effect_authoring, translucency, body_visibility, surface
from cdmw.domain.mesh import emission, shader_controls
from cdmw.domain.new_item.independent import IndependentItemError


_MODULES = (authoring, spec, effect_authoring, translucency, body_visibility, surface, emission, shader_controls)
_TYPES = {value.__name__: value for module in _MODULES for value in vars(module).values()
          if isinstance(value, type) and value.__module__ == module.__name__
          and (is_dataclass(value) or issubclass(value, Enum))}


@lru_cache(maxsize=128)
def _hints(kind):
    return get_type_hints(kind)


def _matches(value, annotation):
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, UnionType):
        return any(_matches(value, arg) for arg in args)
    if origin is tuple:
        return isinstance(value, tuple) and (all(_matches(v, args[0]) for v in value) if len(args) == 2 and args[1] is Ellipsis
                                            else len(value) == len(args) and all(_matches(v, a) for v, a in zip(value, args)))
    if origin in (dict, Mapping):
        return isinstance(value, dict) and all(_matches(k, args[0]) and _matches(v, args[1]) for k, v in value.items())
    if annotation is float:
        try:
            return type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            return False
    if annotation in (bool, int, str, type(None)):
        return type(value) is annotation
    return isinstance(annotation, type) and type(value) is annotation


def encode(value, depth=0):
    if depth > 24:
        raise IndependentItemError("Item recipe is nested too deeply.")
    if isinstance(value, Enum):
        return {"enum": type(value).__name__, "value": value.value}
    if is_dataclass(value):
        if _TYPES.get(type(value).__name__) is not type(value):
            raise IndependentItemError(f"Unsupported portable setting: {type(value).__name__}.")
        return {"type": type(value).__name__, "fields": {f.name: encode(getattr(value, f.name), depth + 1) for f in fields(value)}}
    if isinstance(value, (tuple, list)):
        return [encode(v, depth + 1) for v in value]
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            raise IndependentItemError("Recipe mapping keys must be text.")
        return {"map": {k: encode(v, depth + 1) for k, v in value.items()}}
    if value is None or type(value) in (bool, int, str):
        if isinstance(value, str) and (len(value) > 65536 or "\0" in value):
            raise IndependentItemError("Invalid item recipe text.")
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise IndependentItemError("The item contains a setting that cannot be shared safely.")


def decode(value, depth=0):
    if depth > 24:
        raise IndependentItemError("Item recipe is nested too deeply.")
    if isinstance(value, list):
        if len(value) > 10000:
            raise IndependentItemError("Item recipe contains too many values.")
        return tuple(decode(v, depth + 1) for v in value)
    if isinstance(value, dict):
        if set(value) == {"map"} and isinstance(value["map"], dict):
            return {k: decode(v, depth + 1) for k, v in value["map"].items()}
        kind = _TYPES.get(value.get("type", value.get("enum", "")))
        if kind is not None and issubclass(kind, Enum) and set(value) == {"enum", "value"}:
            return kind(value["value"])
        if kind is not None and is_dataclass(kind) and set(value) == {"type", "fields"}:
            raw = value["fields"]
            if not isinstance(raw, dict) or set(raw) != {f.name for f in fields(kind)}:
                raise IndependentItemError("Unknown or missing item recipe fields.")
            decoded = {k: decode(v, depth + 1) for k, v in raw.items()}
            if any(not _matches(value, _hints(kind)[key]) for key, value in decoded.items()):
                raise IndependentItemError(f"Invalid value type in {kind.__name__}.")
            return kind(**decoded)
        raise IndependentItemError("Unknown item recipe type.")
    return encode(value, depth)
