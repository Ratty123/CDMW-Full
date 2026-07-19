"""Strict wire helpers for the full-CDMW archive worker protocol."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence, TypeVar


class ArchiveContractError(ValueError):
    """Raised when a worker payload does not satisfy a frozen domain contract."""


_EnumT = TypeVar("_EnumT", bound=Enum)


def to_wire(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: to_wire(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): to_wire(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [to_wire(item) for item in value]
    raise TypeError(f"Unsupported archive contract value: {type(value).__name__}")


def require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ArchiveContractError(f"{label} must be an object.")
    return value


def require_sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ArchiveContractError(f"{label} must be an array.")
    return value


def read_string(mapping: Mapping[str, object], key: str, *, default: str | None = None) -> str:
    value = mapping.get(key, default)
    if not isinstance(value, str):
        raise ArchiveContractError(f"{key} must be a string.")
    return value


def read_optional_string(mapping: Mapping[str, object], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ArchiveContractError(f"{key} must be a string or null.")
    return value


def read_int(mapping: Mapping[str, object], key: str, *, default: int | None = None) -> int:
    value = mapping.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArchiveContractError(f"{key} must be an integer.")
    return value


def read_optional_int(mapping: Mapping[str, object], key: str) -> int | None:
    value = mapping.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArchiveContractError(f"{key} must be an integer or null.")
    return value


def read_bool(mapping: Mapping[str, object], key: str, *, default: bool | None = None) -> bool:
    value = mapping.get(key, default)
    if not isinstance(value, bool):
        raise ArchiveContractError(f"{key} must be a boolean.")
    return value


def read_enum(
    mapping: Mapping[str, object],
    key: str,
    enum_type: type[_EnumT],
    *,
    default: _EnumT | None = None,
) -> _EnumT:
    value = mapping.get(key, default.value if default is not None else None)
    if not isinstance(value, str):
        raise ArchiveContractError(f"{key} must be a string enum value.")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ArchiveContractError(f"{key} has unsupported value {value!r}.") from exc


def read_string_tuple(mapping: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = mapping.get(key)
    if value is None:
        return ()
    sequence = require_sequence(value, key)
    if not all(isinstance(item, str) for item in sequence):
        raise ArchiveContractError(f"{key} must contain only strings.")
    return tuple(sequence)  # type: ignore[arg-type]


def compact_optional_fields(payload: Mapping[str, Any]) -> dict[str, object]:
    """Remove optional nulls while retaining explicit false/zero values."""

    return {key: to_wire(value) for key, value in payload.items() if value is not None}


__all__ = [
    "ArchiveContractError",
    "compact_optional_fields",
    "read_bool",
    "read_enum",
    "read_int",
    "read_optional_int",
    "read_optional_string",
    "read_string",
    "read_string_tuple",
    "require_mapping",
    "require_sequence",
    "to_wire",
]
