from __future__ import annotations

import math
from typing import Tuple


def finite_tuple3(value: object, fallback: Tuple[float, float, float]) -> Tuple[float, float, float]:
    if not isinstance(value, (tuple, list)) or len(value) < 3:
        return fallback
    converted: list[float] = []
    for index in range(3):
        try:
            item = float(value[index])
        except (TypeError, ValueError, OverflowError):
            item = fallback[index]
        converted.append(item if math.isfinite(item) else fallback[index])
    return converted[0], converted[1], converted[2]


def int_tuple(value: object) -> Tuple[int, ...]:
    if not isinstance(value, (tuple, list)):
        return ()
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError, OverflowError):
            continue
    return tuple(result)


def int_value(value: object, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def preview_texture_key(
    mesh: object,
    *,
    path_attribute: str,
    image_attribute: str,
    memory_prefix: str,
    mesh_index: int,
) -> str:
    texture_key = str(getattr(mesh, path_attribute, "") or "").strip()
    if not texture_key and getattr(mesh, image_attribute, None) is not None:
        return f"{memory_prefix}:{mesh_index}"
    return texture_key


__all__ = ["finite_tuple3", "int_tuple", "int_value", "preview_texture_key"]
