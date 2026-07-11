"""Prefab edit-format contract."""

from __future__ import annotations


PREFAB_EDIT_JSON_FORMAT = "cdmw.prefab.edit.v1"
PREFAB_EDIT_JSON_VERSION = 1
SUPPORTED_PREFAB_EDIT_ROLES = ("model", "material_sidecar", "texture", "companion_metadata")
SUPPORTED_PREFAB_PLACEMENT_FIELDS = ("_attachedSocketName", "_pivotSocketName", "_partName")


class PrefabEditJsonError(ValueError):
    """Raised when a prefab edit document is stale, malformed, or unsafe."""


__all__ = [
    "PREFAB_EDIT_JSON_FORMAT",
    "PREFAB_EDIT_JSON_VERSION",
    "SUPPORTED_PREFAB_EDIT_ROLES",
    "SUPPORTED_PREFAB_PLACEMENT_FIELDS",
    "PrefabEditJsonError",
]
