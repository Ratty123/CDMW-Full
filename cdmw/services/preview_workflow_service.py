"""Cached, lazy UI boundary for preview preparation workflows."""

from __future__ import annotations

from importlib import import_module


_EXPORTS: dict[str, tuple[str, str]] = {
    "build_binary_sidecar_analysis_json": (
        "cdmw.core.archive_binary_preview",
        "build_binary_sidecar_analysis_json",
    ),
    "build_binary_sidecar_corpus_json": (
        "cdmw.core.archive_binary_preview",
        "build_binary_sidecar_corpus_json",
    ),
    "try_decode_text_like_archive_data": (
        "cdmw.core.archive_binary_preview",
        "try_decode_text_like_archive_data",
    ),
    "attach_scene_preview_textures": (
        "cdmw.core.archive_mesh_import_preview",
        "attach_scene_preview_textures",
    ),
    "build_mesh_import_preview": (
        "cdmw.core.archive_mesh_import_preview",
        "build_mesh_import_preview",
    ),
    "mesh_import_runtime_sibling_mesh_candidates": (
        "cdmw.core.archive_mesh_import_preview",
        "mesh_import_runtime_sibling_mesh_candidates",
    ),
    "parsed_mesh_to_preview_model": (
        "cdmw.core.archive_mesh_import_preview",
        "parsed_mesh_to_preview_model",
    ),
    "FinalPackagePreviewResult": (
        "cdmw.core.final_package_preview",
        "FinalPackagePreviewResult",
    ),
    "MATERIAL_PREFLIGHT_OVERRIDE_WARNING": (
        "cdmw.core.final_package_preview",
        "MATERIAL_PREFLIGHT_OVERRIDE_WARNING",
    ),
    "TEXTURE_PLAN_STATUS_IGNORED_ADVANCED": (
        "cdmw.core.final_package_preview",
        "TEXTURE_PLAN_STATUS_IGNORED_ADVANCED",
    ),
    "TEXTURE_PLAN_STATUS_LIKELY_GREY": (
        "cdmw.core.final_package_preview",
        "TEXTURE_PLAN_STATUS_LIKELY_GREY",
    ),
    "TEXTURE_PLAN_STATUS_READY": (
        "cdmw.core.final_package_preview",
        "TEXTURE_PLAN_STATUS_READY",
    ),
    "TEXTURE_PLAN_STATUS_REVIEW": (
        "cdmw.core.final_package_preview",
        "TEXTURE_PLAN_STATUS_REVIEW",
    ),
    "TEXTURE_PLAN_STATUS_SUPPORT_ONLY": (
        "cdmw.core.final_package_preview",
        "TEXTURE_PLAN_STATUS_SUPPORT_ONLY",
    ),
    "apply_material_preflight_override": (
        "cdmw.core.final_package_preview",
        "apply_material_preflight_override",
    ),
    "build_dds_override_table_row": (
        "cdmw.core.final_package_preview",
        "build_dds_override_table_row",
    ),
    "build_final_package_preview": (
        "cdmw.core.final_package_preview",
        "build_final_package_preview",
    ),
    "build_replacement_texture_plan_rows": (
        "cdmw.core.final_package_preview",
        "build_replacement_texture_plan_rows",
    ),
    "material_preflight_hard_blockers": (
        "cdmw.core.final_package_preview",
        "material_preflight_hard_blockers",
    ),
    "simplified_part_label": ("cdmw.core.final_package_preview", "simplified_part_label"),
    "scene_import_normalizes_texture_v": (
        "cdmw.core.model_preview_orientation",
        "scene_import_normalizes_texture_v",
    ),
    "build_compare_preview_pane_result": (
        "cdmw.core.texture_pipeline.preview",
        "build_compare_preview_pane_result",
    ),
    "collect_compare_relative_paths": (
        "cdmw.core.texture_pipeline.preview",
        "collect_compare_relative_paths",
    ),
    "ensure_dds_display_preview_png": (
        "cdmw.core.texture_pipeline.preview",
        "ensure_dds_display_preview_png",
    ),
}

__all__ = tuple(_EXPORTS)


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
