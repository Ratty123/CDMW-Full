"""Cached, lazy UI boundary for preview rendering operations."""

from __future__ import annotations

from importlib import import_module


_EXPORTS: dict[str, tuple[str, str]] = {
    "find_native_d3d11_host": ("cdmw.rendering.native_d3d11_host", "find_native_d3d11_host"),
    "NativePreviewPackageCacheLease": (
        "cdmw.rendering.native_preview_package_cache",
        "NativePreviewPackageCacheLease",
    ),
    "NATIVE_PREVIEW_PACKAGE_CACHE_SCHEMA": (
        "cdmw.rendering.native_preview_package_cache",
        "NATIVE_PREVIEW_PACKAGE_CACHE_SCHEMA",
    ),
    "acquire_native_preview_package_cache_lease_for_path": (
        "cdmw.rendering.native_preview_package_cache",
        "acquire_native_preview_package_cache_lease_for_path",
    ),
    "clear_native_preview_package_cache": (
        "cdmw.rendering.native_preview_package_cache",
        "clear_native_preview_package_cache",
    ),
    "is_durable_native_preview_package_path": (
        "cdmw.rendering.native_preview_package_cache",
        "is_durable_native_preview_package_path",
    ),
    "lookup_native_preview_package_cache": (
        "cdmw.rendering.native_preview_package_cache",
        "lookup_native_preview_package_cache",
    ),
    "native_preview_package_cache_budget": (
        "cdmw.rendering.native_preview_package_cache",
        "native_preview_package_cache_budget",
    ),
    "native_preview_package_cache_entry_dir": (
        "cdmw.rendering.native_preview_package_cache",
        "native_preview_package_cache_entry_dir",
    ),
    "native_preview_package_prefetch_limit": (
        "cdmw.rendering.native_preview_package_cache",
        "native_preview_package_prefetch_limit",
    ),
    "prune_native_preview_package_cache": (
        "cdmw.rendering.native_preview_package_cache",
        "prune_native_preview_package_cache",
    ),
    "MeshPreviewCacheSignature": (
        "cdmw.rendering.model_preview_prepare",
        "MeshPreviewCacheSignature",
    ),
    "MeshPreviewDirtyFlags": ("cdmw.rendering.model_preview_prepare", "MeshPreviewDirtyFlags"),
    "PreparedModelPreviewData": (
        "cdmw.rendering.model_preview_prepare",
        "PreparedModelPreviewData",
    ),
    "prepare_model_preview": ("cdmw.rendering.model_preview_prepare", "prepare_model_preview"),
    "NativePreviewCoreAttempt": (
        "cdmw.rendering.native_preview_core",
        "NativePreviewCoreAttempt",
    ),
    "NativePreviewCoreServiceClient": (
        "cdmw.rendering.native_preview_core",
        "NativePreviewCoreServiceClient",
    ),
    "find_native_preview_core_binary": (
        "cdmw.rendering.native_preview_core",
        "find_native_preview_core_binary",
    ),
    "native_preview_core_service_process_id": (
        "cdmw.rendering.native_preview_service_state",
        "native_preview_core_service_process_id",
    ),
    "render_settings_to_native_preview_core_dict": (
        "cdmw.rendering.native_preview_core",
        "render_settings_to_native_preview_core_dict",
    ),
    "run_native_preview_core_preview_job": (
        "cdmw.rendering.native_preview_core",
        "run_native_preview_core_preview_job",
    ),
    "shutdown_native_preview_core_service": (
        "cdmw.rendering.native_preview_core",
        "shutdown_native_preview_core_service",
    ),
    "write_isolated_d3d11_preview_package": (
        "cdmw.rendering.native_preview_package_writer",
        "write_isolated_d3d11_preview_package",
    ),
    "StaticModelThumbnailPlan": (
        "cdmw.rendering.static_model_thumbnail",
        "StaticModelThumbnailPlan",
    ),
    "prepare_static_model_thumbnail": (
        "cdmw.rendering.static_model_thumbnail",
        "prepare_static_model_thumbnail",
    ),
    "render_static_model_thumbnail_image": (
        "cdmw.rendering.static_model_thumbnail",
        "render_static_model_thumbnail_image",
    ),
    "MaterialPreviewCombinerResult": (
        "cdmw.rendering.material_combiner",
        "MaterialPreviewCombinerResult",
    ),
    "MaterialPreviewCombinerSettings": (
        "cdmw.rendering.material_combiner",
        "MaterialPreviewCombinerSettings",
    ),
    "_decode_mode_for_input": ("cdmw.rendering.material_combiner", "_decode_mode_for_input"),
    "combine_preview_material": (
        "cdmw.rendering.material_combiner",
        "combine_preview_material",
    ),
    "decode_material_sample": ("cdmw.rendering.material_combiner", "decode_material_sample"),
    "synthesize_material_texture_inputs": (
        "cdmw.rendering.material_combiner",
        "synthesize_material_texture_inputs",
    ),
}
_EXPORTS.update(
    {
        name: ("cdmw.rendering.model_preview_prepare", name)
        for name in (
            "FIT_DISTANCE",
            "OVERLAY_CLIP_EPSILON",
            "BatchRenderDiagnostic",
            "FramebufferVisibilitySample",
            "ModelPreviewDrawBatch",
            "TextureVisibilitySample",
            "alignment_euler_delta_matrix",
            "alignment_euler_xyz_matrix",
            "black_output_triage_lines",
            "build_vertex_blob",
            "clip_preview_line",
            "dds_source_path_for_preview_path",
            "derive_relief_image_from_base",
            "diffuse_probe_source_for_render_mode",
            "enhanced_relief_status",
            "format_support_map_counts",
            "material_combiner_cache_dir",
            "render_mode_uses_derived_relief",
            "sample_base_texture_visibility",
            "sample_framebuffer_visibility",
            "support_map_active_counts_from_diagnostics",
            "support_map_geometry_usable",
            "support_map_slot_counts_from_batches",
        )
    }
)

__all__ = tuple(name for name in _EXPORTS if not name.startswith("_"))


def __getattr__(name: str) -> object:
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))
