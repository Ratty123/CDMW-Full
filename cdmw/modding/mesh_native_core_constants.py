from __future__ import annotations

import os

NATIVE_MESH_CORE_BINARY_NAME = "cdmw-mesh-core.exe" if os.name == "nt" else "cdmw-mesh-core"
NATIVE_MESH_CORE_BACKEND_ID = "cdmw_mesh_core_0.1"
_NATIVE_MESH_EDITOR_NORMAL_OPERATIONS = frozenset(
    {
        "recalculate_normals",
        "weighted_normals",
        "flip_normals",
        "sharpen_normals",
        "soften_normals",
        "copy_normals",
    }
)
_NATIVE_MATERIAL_REPORT_ATTRS = (
    "texture_slots",
    "preview_color",
    "preview_role",
    "preview_texture_path",
    "preview_texture_name",
    "preview_texture_dds_path",
    "preview_texture_flip_vertical",
    "preview_texture_brightness",
    "preview_texture_contrast",
    "preview_texture_saturation",
    "preview_texture_gamma",
    "preview_texture_tint",
    "preview_texture_uv_scale",
    "preview_base_texture_default_path",
    "preview_base_texture_default_name",
    "preview_vertex_color_mean",
    "preview_vertex_alpha_mean",
    "preview_vertex_alpha_min",
    "preview_vertex_color_count",
    "preview_normal_texture_path",
    "preview_normal_texture_name",
    "preview_normal_texture_dds_path",
    "preview_normal_texture_strength",
    "preview_material_texture_path",
    "preview_material_texture_name",
    "preview_material_texture_dds_path",
    "preview_material_texture_type",
    "preview_material_texture_subtype",
    "preview_material_texture_packed_channels",
    "preview_material_texture_inputs",
    "preview_material_parameters",
    "preview_material_texture_default_path",
    "preview_material_texture_default_name",
    "preview_height_texture_path",
    "preview_height_texture_name",
    "preview_height_texture_dds_path",
    "preview_alpha_mode",
    "preview_double_sided",
    "preview_sidecar_shader_family",
    "cdmw_material_authority_profile",
    "cdmw_material_authority_contract",
    "cdmw_source_material_name",
    "cdmw_target_material_name",
    "cdmw_target_material_slot_index",
    "cdmw_material_slot_kind",
    "cdmw_source_texture_set_key",
    "cdmw_material_route_status",
    "cdmw_material_route_reason",
    "preview_native_material_overrides",
    "cdmw_mesh_edit_material_source_submesh_index",
)
_NATIVE_PREVIEW_MATERIAL_OVERRIDE_KEYS = (
    "texture_brightness",
    "roughness",
    "metalness",
    "specular",
    "height_scale",
    "emissive_intensity",
    "emissive_color",
    "contrast",
    "saturation",
    "gamma",
    "tint_color",
)

Vec3 = tuple[float, float, float]
Vec2 = tuple[float, float]
Face = tuple[int, int, int]

NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR = "cdmw_native_mesh_history_vertex_delta"
_TRANSIENT_NATIVE_SUBMESH_ATTRS = frozenset(
    {
        "cdmw_native_preview_triangle_group",
        "cdmw_native_preview_vertex_update_group",
        NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR,
    }
)
_NATIVE_MESH_SESSION_TOKEN_ATTR = "_cdmw_native_mesh_session_token"
