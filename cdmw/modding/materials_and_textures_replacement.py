"""Replace Materials and Textures Only preset helpers.

The sixth operation in the plan's matrix, and the one that had no command. It
takes an external model for its materials and texture files and leaves the
target's geometry alone: the mesh bytes are not rewritten at all, which is what
makes "geometry hash remains unchanged" a fact about the output rather than a
hope about the writer.

Material handling is deliberately identical to Full Import Model Replacement --
the imported model owns the bindings and the texture files either way, and
having two answers to that would be the thing `MeshOperationSpec` exists to
prevent. The whole difference is `writes_geometry`, which the operation carries
and the commit boundary reads.
"""

from __future__ import annotations

import dataclasses

from cdmw.domain.mesh.operation_spec import OPERATION_SPECS, OperationKind
from cdmw.modding.static_mesh_types import StaticMeshReplacementOptions


MATERIALS_AND_TEXTURES_PROFILE = "material_authority_detail_mask"
MATERIALS_AND_TEXTURES_TITLE = "Replace Materials and Textures Only"
MATERIALS_AND_TEXTURES_SETUP_TITLE = "Replace Materials and Textures Only Setup"
MATERIALS_AND_TEXTURES_PLACEMENT_NOTE = (
    "Placement is not used by this workflow. The selected game item keeps its own mesh; the "
    "imported model supplies only the material bindings and the texture files, so nothing here "
    "changes the geometry that ships."
)


def apply_materials_and_textures_only_preset(
    options: StaticMeshReplacementOptions | None = None,
) -> StaticMeshReplacementOptions:
    """Force the source-owned material route while retaining target geometry."""

    preserve_tuning = options is not None
    base = options or StaticMeshReplacementOptions()
    return dataclasses.replace(
        base,
        rebuild_material_sidecar=True,
        complete_external_swap=True,
        neutralize_inherited_material_layers=True,
        complete_external_material_reset=True,
        enable_missing_base_color_parameters=True,
        texture_output_size_mode="source",
        complete_swap_atlas_mode="auto_when_needed",
        complete_swap_material_profile=(
            base.complete_swap_material_profile if preserve_tuning else MATERIALS_AND_TEXTURES_PROFILE
        ),
        accent_glow_strength=base.accent_glow_strength if preserve_tuning else 0.0,
        prune_removed_target_texture_parameters=True,
        prune_unmapped_original_texture_parameters=True,
        # The transform is deliberately untouched. Full Import forces an
        # alignment because it is replacing the mesh; here there is no mesh to
        # align, and forcing one would imply the geometry moves.
        operation_spec=OPERATION_SPECS[OperationKind.REPLACE_MATERIALS_AND_TEXTURES],
    )


def materials_and_textures_external_file_filter() -> str:
    return (
        "External Model Files (*.obj *.dae *.gltf *.glb *.zip);;"
        "Wavefront OBJ (*.obj);;"
        "Collada DAE (*.dae);;"
        "glTF / GLB (*.gltf *.glb);;"
        "Model ZIP (*.zip)"
    )


__all__ = [
    "MATERIALS_AND_TEXTURES_PLACEMENT_NOTE",
    "MATERIALS_AND_TEXTURES_PROFILE",
    "MATERIALS_AND_TEXTURES_SETUP_TITLE",
    "MATERIALS_AND_TEXTURES_TITLE",
    "apply_materials_and_textures_only_preset",
    "materials_and_textures_external_file_filter",
]
