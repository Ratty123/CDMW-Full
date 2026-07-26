"""Canonical material surface-category vocabulary shared with the renderer.

One category decision crosses three languages. Python classifies a batch and
emits a category *string*; the .NET resident material set maps that string to a
float *code*; the HLSL pixel shader decodes the float back into per-category
booleans with range comparisons. Nothing previously tied the three together, so
adding a category on the Python side silently degraded to code 0 -- no import
error, no failing test, just a surface that quietly lost its response.

This module is the single definition. It does not decide which category a batch
gets; ``native_preview_material_contract._resolved_batch_material_category``
still owns that. It fixes the vocabulary and the wire codes so the three
representations cannot drift apart unnoticed, which
``tests/test_material_category_contract.py`` enforces against the real C# and
HLSL sources.

Codes are a wire format. Renumbering one breaks every prepared package that
already carries the old number, so append new categories at the end.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping


MATERIAL_CATEGORY_CONTRACT_SCHEMA_VERSION = 1

#: Emitted when classification found no authoritative surface evidence. Carries
#: code 0, which the shader reads as "no source category" rather than as a
#: category in its own right.
MATERIAL_CATEGORY_UNCLASSIFIED = "generic"

_CODES: dict[str, int] = {
    MATERIAL_CATEGORY_UNCLASSIFIED: 0,
    "metal": 1,
    "leather": 2,
    "wood": 3,
    "cloth": 4,
    "skin": 5,
    "hair": 6,
    "glass": 7,
    "gem": 8,
    "stone": 9,
    "eye": 10,
    "tooth": 11,
}

#: Category name -> wire code, in code order.
MATERIAL_CATEGORY_CODES: Mapping[str, int] = MappingProxyType(_CODES)

#: The categories that carry a nonzero code, in code order.
CLASSIFIED_MATERIAL_CATEGORIES: tuple[str, ...] = tuple(
    name for name, code in _CODES.items() if code != 0
)

#: Every category a classifier may emit, in code order.
MATERIAL_CATEGORIES: tuple[str, ...] = tuple(_CODES)


def material_category_code(category: object) -> int:
    """Wire code for a category name; 0 for unknown, empty, or unclassified.

    Matches the .NET side, which trims and compares case-insensitively and falls
    back to 0 rather than raising.
    """
    name = str(category or "").strip().casefold()
    return _CODES.get(name, 0)


def material_category_for_code(code: object) -> str:
    """Inverse of :func:`material_category_code`, for diagnostics and evidence."""
    try:
        wanted = int(code)
    except (TypeError, ValueError, OverflowError):
        return MATERIAL_CATEGORY_UNCLASSIFIED
    for name, value in _CODES.items():
        if value == wanted:
            return name
    return MATERIAL_CATEGORY_UNCLASSIFIED


def is_known_material_category(category: object) -> bool:
    """Whether the name is in the vocabulary at all, unclassified included."""
    return str(category or "").strip().casefold() in _CODES


__all__ = [
    "CLASSIFIED_MATERIAL_CATEGORIES",
    "MATERIAL_CATEGORIES",
    "MATERIAL_CATEGORY_CODES",
    "MATERIAL_CATEGORY_CONTRACT_SCHEMA_VERSION",
    "MATERIAL_CATEGORY_UNCLASSIFIED",
    "is_known_material_category",
    "material_category_code",
    "material_category_for_code",
]
