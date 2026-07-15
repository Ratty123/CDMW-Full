from __future__ import annotations

from pathlib import Path
from typing import Dict, Mapping

from cdmw.models import PreparedModelPreviewBatch


_NATIVE_MATERIAL_OVERRIDE_KEYS = frozenset(
    {
        "alpha_cutoff",
        "alpha_threshold",
        "base_tint_strength",
        "height_amount",
        "height_scale",
        "material_analysis",
        "material_category",
        "material_category_confidence",
        "material_category_reason",
        "material_finish",
        "material_layers",
        "material_response_disposition",
        "material_response_promoted",
        "material_shader_family",
        "metalness",
        "native_base_quality",
        "native_material_hints",
        "normal_strength",
        "primary_material_layer",
        "roughness",
        "specular",
    }
)


def _manifest_source_path_is_local_file(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        return Path(text).expanduser().is_file()
    except OSError:
        return False


def _sanitize_nonfile_manifest_source_paths(value: object) -> object:
    if isinstance(value, Mapping):
        sanitized: Dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text == "source_path" and str(item or "").strip() and not _manifest_source_path_is_local_file(item):
                sanitized["source_reference"] = str(item or "")
                continue
            sanitized[key_text] = _sanitize_nonfile_manifest_source_paths(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_nonfile_manifest_source_paths(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_nonfile_manifest_source_paths(item) for item in value]
    return value


def _jsonable_native_material_override(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable_native_material_override(item)
            for key, item in value.items()
            if isinstance(key, (str, int, float, bool))
        }
    if isinstance(value, (tuple, list)):
        return [_jsonable_native_material_override(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _native_material_overrides_for_batch(batch: PreparedModelPreviewBatch) -> Dict[str, object]:
    raw_overrides = getattr(batch, "preview_native_material_overrides", None)
    if not isinstance(raw_overrides, Mapping):
        return {}
    return {
        str(key): _jsonable_native_material_override(value)
        for key, value in raw_overrides.items()
        if str(key) in _NATIVE_MATERIAL_OVERRIDE_KEYS
    }


__all__ = [
    "_NATIVE_MATERIAL_OVERRIDE_KEYS",
    "_jsonable_native_material_override",
    "_manifest_source_path_is_local_file",
    "_native_material_overrides_for_batch",
    "_sanitize_nonfile_manifest_source_paths",
]
