"""Static preview cache-key helpers for static replacement."""

from __future__ import annotations

import json
from collections.abc import MutableMapping, Sequence


def model_has_preview_texture_keys(model: object) -> bool:
    return any(
        bool(
            str(getattr(mesh, "preview_texture_path", "") or "").strip()
            or str(getattr(mesh, "preview_normal_texture_path", "") or "").strip()
            or str(getattr(mesh, "preview_material_texture_path", "") or "").strip()
            or str(getattr(mesh, "preview_height_texture_path", "") or "").strip()
        )
        for mesh in getattr(model, "meshes", ()) or ()
    )


def static_preview_prepared_cache_key(
    model: object,
    *,
    source_preview_cache_key: str,
    active_preview_mode: str,
    cache_suffix: str,
    selected_preview_indices: Sequence[int] | None,
    highlighted_source_indices: Sequence[int],
    highlighted_original_indices: Sequence[int],
    texture_override_preview_specs: Sequence[Sequence[object]],
    material_authority_preview_signature: object,
    minimum_face_count: int = 40_000,
) -> str:
    face_count = int(getattr(model, "face_count", 0) or 0)
    if not source_preview_cache_key or (face_count < int(minimum_face_count) and not model_has_preview_texture_keys(model)):
        return ""
    texture_specs = []
    for spec in tuple(texture_override_preview_specs or ()):
        if len(spec) < 5:
            continue
        target_name, slot_kind, preview_texture_path, source_name, source_indices = spec[:5]
        texture_specs.append(
            (target_name, slot_kind, preview_texture_path, source_name, tuple(source_indices or ()))
        )
    prepared_payload = {
        "source": source_preview_cache_key,
        "mode": active_preview_mode,
        "suffix": cache_suffix,
        "selected": tuple(selected_preview_indices or ()),
        "highlight_sources": tuple(sorted(int(index) for index in highlighted_source_indices)),
        "highlight_original": tuple(sorted(int(index) for index in highlighted_original_indices)),
        "texture_specs": tuple(texture_specs),
        "material_authority_preview_signature": str(material_authority_preview_signature or ""),
        "summary": str(getattr(model, "summary", "") or ""),
    }
    return json.dumps(prepared_payload, sort_keys=True, separators=(",", ":"))


def cached_static_preview_geometry(geometry_cache: MutableMapping[str, object], cache_key: str, *, live_mesh_edit: bool) -> object | None:
    return None if live_mesh_edit else geometry_cache.get(cache_key)


def static_preview_geometry_cache_payload(
    source_model: object,
    *,
    mapped_preview: bool,
    direct_source_preview_index_map: MutableMapping[int, int],
    source_overlay_preview_index_map: MutableMapping[int, int],
    preview_submesh_index_map: MutableMapping[int, int],
) -> tuple[object, bool, dict[int, int], dict[int, int], dict[int, int]]:
    return (
        source_model, bool(mapped_preview), dict(direct_source_preview_index_map),
        dict(source_overlay_preview_index_map), dict(preview_submesh_index_map),
    )


def restore_static_preview_geometry_cache_payload(
    cached_preview: Sequence[object],
    *,
    direct_source_preview_index_map: MutableMapping[int, int],
    source_overlay_preview_index_map: MutableMapping[int, int],
    preview_submesh_index_map: MutableMapping[int, int],
) -> tuple[object, bool]:
    source_model, mapped_preview, source_index_map, overlay_index_map, submesh_index_map = tuple(cached_preview)[:5]
    direct_source_preview_index_map.clear()
    direct_source_preview_index_map.update(source_index_map)
    source_overlay_preview_index_map.clear()
    source_overlay_preview_index_map.update(overlay_index_map)
    preview_submesh_index_map.clear()
    preview_submesh_index_map.update(submesh_index_map)
    return source_model, bool(mapped_preview)


def store_static_preview_cache_entry(
    cache: MutableMapping[str, object],
    cache_key: str,
    cached_value: object,
    *,
    cache_limit: int = 8,
    paired_cache_to_clear: MutableMapping[str, object] | None = None,
) -> object:
    if len(cache) >= int(cache_limit):
        cache.clear()
        if paired_cache_to_clear is not None:
            paired_cache_to_clear.clear()
    cache[cache_key] = cached_value
    return cached_value


__all__ = [
    "cached_static_preview_geometry",
    "model_has_preview_texture_keys",
    "restore_static_preview_geometry_cache_payload",
    "static_preview_geometry_cache_payload",
    "static_preview_prepared_cache_key",
    "store_static_preview_cache_entry",
]
