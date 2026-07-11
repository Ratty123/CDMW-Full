"""Pure cache helpers for static replacement D3D11 preview packages."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping, MutableMapping
import hashlib
from pathlib import Path

from cdmw.services.preview_rendering_service import MeshPreviewDirtyFlags


def alignment_d3d11_cache_display_class(display_mode: str) -> str:
    normalized = str(display_mode or "side_by_side").strip() or "side_by_side"
    return "replacement_only" if normalized == "replacement_only" else "with_original"


def alignment_d3d11_package_is_cached(package_dir: object, package_cache: object) -> bool:
    if package_dir is None:
        return False
    try:
        package_path = Path(package_dir).resolve()
    except (OSError, TypeError, ValueError):
        return False
    if not isinstance(package_cache, OrderedDict):
        return False
    for entry in package_cache.values():
        if not isinstance(entry, Mapping):
            continue
        try:
            if Path(entry.get("package_dir", "")).resolve() == package_path:
                return True
        except (OSError, TypeError, ValueError):
            continue
    return False


def alignment_d3d11_package_cache_get(
    cache_key: str,
    package_cache: object,
    *,
    cleanup_package: Callable[[object], None],
) -> Mapping[str, object] | None:
    key = str(cache_key or "")
    if not key:
        return None
    if not isinstance(package_cache, OrderedDict):
        return None
    entry = package_cache.get(key)
    if not isinstance(entry, Mapping):
        return None
    package_dir = entry.get("package_dir")
    try:
        package_path = Path(package_dir)
    except TypeError:
        package_cache.pop(key, None)
        return None
    if not (package_path / "manifest.json").is_file():
        package_cache.pop(key, None)
        cleanup_package(package_path)
        return None
    package_cache.move_to_end(key)
    return entry


def alignment_d3d11_package_cache_put(
    cache_key: str,
    package_dir: Path,
    package_cache: object,
    *,
    display_class: str,
    display_mode: str,
    package_quality: str,
    prepare_ms: float,
    package_ms: float,
    created: float,
    limit: object,
) -> tuple[OrderedDict, tuple[object, ...]]:
    cache = package_cache if isinstance(package_cache, OrderedDict) else OrderedDict()
    key = str(cache_key or "")
    if not key:
        return cache, ()
    cache[key] = {
        "package_dir": Path(package_dir),
        "display_class": str(display_class or "with_original"),
        "display_mode": str(display_mode or "side_by_side"),
        "package_quality": str(package_quality or "normal"),
        "prepare_ms": float(prepare_ms or 0.0),
        "package_ms": float(package_ms or 0.0),
        "created": float(created or 0.0),
    }
    cache.move_to_end(key)
    try:
        max_entries = max(1, int(limit or 12))
    except (TypeError, ValueError):
        max_entries = 12
    evicted_package_dirs = []
    while len(cache) > max_entries:
        _old_key, old_entry = cache.popitem(last=False)
        if isinstance(old_entry, Mapping):
            evicted_package_dirs.append(old_entry.get("package_dir"))
    return cache, tuple(evicted_package_dirs)


def alignment_d3d11_invalidate_package_cache(
    state: Mapping[str, object],
    reason: str = "geometry",
    *,
    cleanup_package: Callable[[Path, int], None],
) -> None:
    normalized_reason = str(reason or "geometry").strip().lower()
    if normalized_reason in {"material", "mesh_edit_mode"}:
        if normalized_reason == "material":
            state["last_cache_event"] = "material_dirty"  # type: ignore[index]
        else:
            state["last_cache_event"] = "mode_dirty"  # type: ignore[index]
        state["last_cache_reason"] = normalized_reason  # type: ignore[index]
        return
    package_cache = state.get("package_cache")
    if not isinstance(package_cache, OrderedDict) or not package_cache:
        return
    active_package = state.get("active_package")
    active_path: Path | None = None
    try:
        active_path = Path(active_package).resolve() if active_package is not None else None
    except (OSError, TypeError, ValueError):
        active_path = None
    entries = list(package_cache.values())
    package_cache.clear()
    state["active_package_cache_key"] = ""  # type: ignore[index]
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        package_dir = entry.get("package_dir")
        try:
            package_path = Path(package_dir).resolve()
        except (OSError, TypeError, ValueError):
            continue
        delay_ms = 5000 if active_path is not None and package_path == active_path else 0
        cleanup_package(package_path, delay_ms)
    state["last_cache_event"] = "cleared"  # type: ignore[index]
    state["last_cache_reason"] = normalized_reason  # type: ignore[index]


def alignment_d3d11_record_package_request_metadata(
    state: MutableMapping[str, object],
    *,
    package_quality: str,
    rebuild_reason: str,
) -> None:
    normalized_reason = str(rebuild_reason or "geometry").strip().lower() or "geometry"
    state["package_quality"] = str(package_quality or "normal")
    state["last_rebuild_reason"] = normalized_reason
    state["last_cache_reason"] = normalized_reason


def alignment_d3d11_reset_package_quality(state: MutableMapping[str, object]) -> None:
    state["package_quality"] = "normal"


def alignment_d3d11_record_cache_hit_metadata(
    state: MutableMapping[str, object],
    cache_entry: Mapping[str, object],
    *,
    package_quality: str,
) -> str:
    quality = str(cache_entry.get("package_quality", package_quality) or package_quality)
    state["prepare_ms"] = float(cache_entry.get("prepare_ms", 0.0) or 0.0)
    state["package_ms"] = float(cache_entry.get("package_ms", 0.0) or 0.0)
    state["package_quality"] = quality
    state["last_cache_event"] = "hit"
    return quality


def alignment_d3d11_record_cache_lookup_result(
    state: MutableMapping[str, object],
    cache_key: str,
) -> str:
    event = "bypass" if not str(cache_key or "") else "miss"
    state["last_cache_event"] = event
    return event


def alignment_d3d11_record_package_timing(
    state: MutableMapping[str, object],
    *,
    prepare_ms: float,
    package_ms: float,
) -> None:
    state["prepare_ms"] = float(prepare_ms)
    state["package_ms"] = float(package_ms)


def alignment_d3d11_store_package_cache(state: MutableMapping[str, object], package_cache: OrderedDict) -> None:
    state["package_cache"] = package_cache


def alignment_d3d11_dirty_flags_for_reason(reason: str) -> MeshPreviewDirtyFlags:
    normalized = str(reason or "geometry").strip().lower()
    if normalized == "material":
        return MeshPreviewDirtyFlags(material=True)
    if normalized == "texture_uv":
        return MeshPreviewDirtyFlags(uv=True, material=True)
    if normalized == "mode_missing_original":
        return MeshPreviewDirtyFlags(render_settings=True)
    if normalized == "selection":
        return MeshPreviewDirtyFlags(selection=True)
    return MeshPreviewDirtyFlags(geometry=True)


def alignment_d3d11_model_cache_signature(
    model: object,
    *,
    file_signature: Callable[[object], tuple[str, int, int]],
    sample_sequence: Callable[[object], tuple],
) -> str:
    mesh_signatures = []
    for mesh in getattr(model, "meshes", ()) or ():
        raw_native_overrides = getattr(mesh, "preview_native_material_overrides", {}) or {}
        if not isinstance(raw_native_overrides, Mapping):
            raw_native_overrides = {}
        native_overrides = tuple(
            sorted(
                (str(key), repr(value))
                for key, value in raw_native_overrides.items()
            )
        )
        material_inputs = tuple(
            (
                str(getattr(item, "parameter_name", "") or ""),
                str(getattr(item, "slot_kind", "") or ""),
                str(getattr(item, "semantic_type", "") or ""),
                str(getattr(item, "semantic_subtype", "") or ""),
                str(getattr(item, "source_texture_path", "") or ""),
                str(getattr(item, "source_dds_path", "") or ""),
                str(getattr(item, "preview_texture_path", "") or ""),
                file_signature(getattr(item, "source_texture_path", "")),
                file_signature(getattr(item, "source_dds_path", "")),
                file_signature(getattr(item, "preview_texture_path", "")),
                tuple(getattr(item, "packed_channels", ()) or ()),
                tuple(
                    (
                        str(getattr(parameter, "parameter_kind", "") or ""),
                        str(getattr(parameter, "parameter_name", "") or ""),
                        str(getattr(parameter, "value", "") or ""),
                        str(getattr(parameter, "numeric_value", "") or ""),
                    )
                    for parameter in tuple(getattr(item, "material_parameters", ()) or ())
                ),
            )
            for item in tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ())[:24]
        )
        mesh_signatures.append(
            (
                str(getattr(mesh, "material_name", "") or ""),
                str(getattr(mesh, "texture_name", "") or ""),
                str(getattr(mesh, "preview_role", "") or ""),
                int(getattr(mesh, "source_submesh_index", -1) or -1),
                len(getattr(mesh, "positions", ()) or ()),
                len(getattr(mesh, "texture_coordinates", ()) or ()),
                len(getattr(mesh, "indices", ()) or ()),
                sample_sequence(getattr(mesh, "positions", ()) or ()),
                sample_sequence(getattr(mesh, "texture_coordinates", ()) or ()),
                sample_sequence(getattr(mesh, "indices", ()) or ()),
                str(getattr(mesh, "preview_texture_path", "") or ""),
                str(getattr(mesh, "preview_texture_dds_path", "") or ""),
                str(getattr(mesh, "preview_normal_texture_path", "") or ""),
                str(getattr(mesh, "preview_normal_texture_dds_path", "") or ""),
                str(getattr(mesh, "preview_material_texture_path", "") or ""),
                str(getattr(mesh, "preview_material_texture_dds_path", "") or ""),
                str(getattr(mesh, "preview_height_texture_path", "") or ""),
                str(getattr(mesh, "preview_height_texture_dds_path", "") or ""),
                file_signature(getattr(mesh, "preview_texture_path", "")),
                file_signature(getattr(mesh, "preview_texture_dds_path", "")),
                file_signature(getattr(mesh, "preview_material_texture_path", "")),
                file_signature(getattr(mesh, "preview_material_texture_dds_path", "")),
                getattr(mesh, "preview_texture_flip_vertical", None),
                tuple(getattr(mesh, "preview_texture_tint", ()) or ()),
                float(getattr(mesh, "preview_texture_brightness", 1.0) or 1.0),
                tuple(getattr(mesh, "preview_texture_uv_scale", ()) or ()),
                tuple(getattr(mesh, "preview_vertex_color_mean", ()) or ()),
                getattr(mesh, "preview_vertex_alpha_mean", None),
                getattr(mesh, "preview_vertex_alpha_min", None),
                int(getattr(mesh, "preview_vertex_color_count", 0) or 0),
                bool(getattr(mesh, "preview_double_sided", False)),
                native_overrides,
                material_inputs,
            )
        )
    signature = (
        str(getattr(model, "path", "") or ""),
        str(getattr(model, "format", "") or ""),
        int(getattr(model, "mesh_count", 0) or 0),
        int(getattr(model, "vertex_count", 0) or 0),
        int(getattr(model, "face_count", 0) or 0),
        tuple(getattr(model, "normalization_center", ()) or ()),
        float(getattr(model, "normalization_scale", 1.0) or 1.0),
        tuple(mesh_signatures),
    )
    encoded = repr(signature).encode("utf-8", errors="replace")
    return hashlib.sha1(encoded).hexdigest()


def alignment_d3d11_geometry_cache_key(
    model: object,
    *,
    display_mode: str,
    modify_original_clone_mode: bool,
    sequence_digest: Callable[[object], tuple[int, str]],
) -> str:
    mesh_signatures = []
    for mesh in getattr(model, "meshes", ()) or ():
        mesh_signatures.append(
            (
                int(getattr(mesh, "source_submesh_index", -1) or -1),
                sequence_digest(getattr(mesh, "positions", ()) or ()),
                sequence_digest(getattr(mesh, "normals", ()) or ()),
                sequence_digest(getattr(mesh, "texture_coordinates", ()) or ()),
                sequence_digest(getattr(mesh, "indices", ()) or ()),
                bool(getattr(mesh, "preview_double_sided", False)),
            )
        )
    signature = (
        "alignment_d3d11_geometry_v1",
        str(getattr(model, "path", "") or ""),
        str(getattr(model, "format", "") or ""),
        int(getattr(model, "mesh_count", 0) or 0),
        int(getattr(model, "vertex_count", 0) or 0),
        int(getattr(model, "face_count", 0) or 0),
        tuple(getattr(model, "normalization_center", ()) or ()),
        float(getattr(model, "normalization_scale", 1.0) or 1.0),
        alignment_d3d11_cache_display_class(display_mode),
        bool(modify_original_clone_mode),
        tuple(mesh_signatures),
    )
    encoded = repr(signature).encode("utf-8", errors="replace")
    return hashlib.sha1(encoded).hexdigest()


def alignment_d3d11_material_cache_key(
    model: object,
    settings: object,
    *,
    package_quality: str,
    donor_material_plan_payload: object,
    material_authority_preview_signature: str,
    file_signature: Callable[[object], tuple[str, int, int]],
) -> str:
    package_settings = (
        bool(getattr(settings, "use_textures_by_default", True)),
        bool(getattr(settings, "high_quality_by_default", True)),
        int(getattr(settings, "preview_texture_max_dimension", 0) or 0),
        int(getattr(settings, "low_quality_texture_max_dimension", 0) or 0),
        bool(getattr(settings, "disable_all_support_maps", False)),
        bool(getattr(settings, "disable_normal_map", False)),
        bool(getattr(settings, "disable_material_map", False)),
        bool(getattr(settings, "disable_height_map", False)),
        bool(getattr(settings, "flip_texture_v", False)),
        str(getattr(settings, "visible_texture_mode", "") or ""),
        str(getattr(settings, "alpha_handling_mode", "") or ""),
        str(package_quality or "normal"),
    )
    material_authority_payload = {
        "donor_material_plans": donor_material_plan_payload,
        "material_authority_preview_signature": str(material_authority_preview_signature or ""),
    }
    mesh_signatures = []
    for mesh in getattr(model, "meshes", ()) or ():
        raw_native_overrides = getattr(mesh, "preview_native_material_overrides", {}) or {}
        if not isinstance(raw_native_overrides, Mapping):
            raw_native_overrides = {}
        native_overrides = tuple(
            sorted(
                (str(key), repr(value))
                for key, value in raw_native_overrides.items()
            )
        )
        material_inputs = tuple(
            (
                str(getattr(item, "parameter_name", "") or ""),
                str(getattr(item, "slot_kind", "") or ""),
                str(getattr(item, "semantic_type", "") or ""),
                str(getattr(item, "semantic_subtype", "") or ""),
                str(getattr(item, "source_texture_path", "") or ""),
                str(getattr(item, "source_dds_path", "") or ""),
                str(getattr(item, "preview_texture_path", "") or ""),
                file_signature(getattr(item, "source_texture_path", "")),
                file_signature(getattr(item, "source_dds_path", "")),
                file_signature(getattr(item, "preview_texture_path", "")),
                tuple(getattr(item, "packed_channels", ()) or ()),
                tuple(
                    (
                        str(getattr(parameter, "parameter_kind", "") or ""),
                        str(getattr(parameter, "parameter_name", "") or ""),
                        str(getattr(parameter, "value", "") or ""),
                        str(getattr(parameter, "numeric_value", "") or ""),
                    )
                    for parameter in tuple(getattr(item, "material_parameters", ()) or ())
                ),
            )
            for item in tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ())[:24]
        )
        mesh_signatures.append(
            (
                str(getattr(mesh, "material_name", "") or ""),
                str(getattr(mesh, "texture_name", "") or ""),
                str(getattr(mesh, "preview_texture_path", "") or ""),
                str(getattr(mesh, "preview_texture_dds_path", "") or ""),
                str(getattr(mesh, "preview_normal_texture_path", "") or ""),
                str(getattr(mesh, "preview_normal_texture_dds_path", "") or ""),
                str(getattr(mesh, "preview_material_texture_path", "") or ""),
                str(getattr(mesh, "preview_material_texture_dds_path", "") or ""),
                str(getattr(mesh, "preview_height_texture_path", "") or ""),
                str(getattr(mesh, "preview_height_texture_dds_path", "") or ""),
                file_signature(getattr(mesh, "preview_texture_path", "")),
                file_signature(getattr(mesh, "preview_texture_dds_path", "")),
                file_signature(getattr(mesh, "preview_normal_texture_path", "")),
                file_signature(getattr(mesh, "preview_normal_texture_dds_path", "")),
                file_signature(getattr(mesh, "preview_material_texture_path", "")),
                file_signature(getattr(mesh, "preview_material_texture_dds_path", "")),
                file_signature(getattr(mesh, "preview_height_texture_path", "")),
                file_signature(getattr(mesh, "preview_height_texture_dds_path", "")),
                getattr(mesh, "preview_texture_flip_vertical", None),
                tuple(getattr(mesh, "preview_texture_tint", ()) or ()),
                float(getattr(mesh, "preview_texture_brightness", 1.0) or 1.0),
                tuple(getattr(mesh, "preview_texture_uv_scale", ()) or ()),
                tuple(getattr(mesh, "preview_vertex_color_mean", ()) or ()),
                getattr(mesh, "preview_vertex_alpha_mean", None),
                getattr(mesh, "preview_vertex_alpha_min", None),
                int(getattr(mesh, "preview_vertex_color_count", 0) or 0),
                str(getattr(mesh, "preview_alpha_mode", "") or ""),
                bool(getattr(mesh, "preview_double_sided", False)),
                native_overrides,
                material_inputs,
            )
        )
    signature = (
        "alignment_d3d11_material_v1",
        package_settings,
        material_authority_payload,
        tuple(mesh_signatures),
    )
    encoded = repr(signature).encode("utf-8", errors="replace")
    return hashlib.sha1(encoded).hexdigest()


__all__ = [
    "alignment_d3d11_cache_display_class",
    "alignment_d3d11_dirty_flags_for_reason",
    "alignment_d3d11_geometry_cache_key",
    "alignment_d3d11_material_cache_key",
    "alignment_d3d11_model_cache_signature",
    "alignment_d3d11_invalidate_package_cache",
    "alignment_d3d11_package_cache_get",
    "alignment_d3d11_package_cache_put",
    "alignment_d3d11_package_is_cached",
    "alignment_d3d11_record_cache_hit_metadata",
    "alignment_d3d11_record_cache_lookup_result",
    "alignment_d3d11_record_package_request_metadata",
    "alignment_d3d11_record_package_timing",
    "alignment_d3d11_reset_package_quality",
    "alignment_d3d11_store_package_cache",
]
