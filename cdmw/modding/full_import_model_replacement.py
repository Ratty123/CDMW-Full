"""Full Import Model Replacement preset helpers."""

from __future__ import annotations

import dataclasses

from cdmw.modding.static_mesh_types import StaticMeshReplacementOptions


FULL_IMPORT_MODEL_REPLACEMENT_PROFILE = "material_authority_detail_mask"
FULL_IMPORT_MODEL_REPLACEMENT_TITLE = "Full Import Model Replacement"
FULL_IMPORT_MODEL_REPLACEMENT_SETUP_TITLE = "Full Import Model Replacement Setup"
FULL_IMPORT_MODEL_REPLACEMENT_PLACEMENT_NOTE = (
    "Review only offset, rotation, and scale. This workflow uses the selected game item as the "
    "runtime slot, but the imported model owns the visible mesh, generated textures, and material "
    "sidecar output."
)


def apply_full_import_model_replacement_preset(
    options: StaticMeshReplacementOptions | None = None,
) -> StaticMeshReplacementOptions:
    base = options or StaticMeshReplacementOptions()
    return dataclasses.replace(
        base,
        transform=dataclasses.replace(base.transform, scale_to_original_length=True),
        rebuild_material_sidecar=True,
        complete_external_swap=True,
        full_import_model_replacement=True,
        neutralize_inherited_material_layers=True,
        complete_external_material_reset=True,
        enable_missing_base_color_parameters=True,
        texture_output_size_mode="source",
        complete_swap_atlas_mode="auto_when_needed",
        complete_swap_material_profile=FULL_IMPORT_MODEL_REPLACEMENT_PROFILE,
        accent_glow_strength=0.0,
        prune_removed_target_texture_parameters=True,
        prune_unmapped_original_texture_parameters=True,
    )


def full_import_model_replacement_external_file_filter() -> str:
    return (
        "External Model Files (*.obj *.dae *.gltf *.glb *.zip);;"
        "Wavefront OBJ (*.obj);;"
        "Collada DAE (*.dae);;"
        "glTF / GLB (*.gltf *.glb);;"
        "Model ZIP (*.zip)"
    )


__all__ = [
    "FULL_IMPORT_MODEL_REPLACEMENT_PLACEMENT_NOTE",
    "FULL_IMPORT_MODEL_REPLACEMENT_PROFILE",
    "FULL_IMPORT_MODEL_REPLACEMENT_SETUP_TITLE",
    "FULL_IMPORT_MODEL_REPLACEMENT_TITLE",
    "apply_full_import_model_replacement_preset",
    "full_import_model_replacement_external_file_filter",
]
