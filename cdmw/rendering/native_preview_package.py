"""Compatibility facade for native D3D11 preview package writing."""

from __future__ import annotations

from cdmw.rendering.native_preview_payloads import (
    ISOLATED_PREVIEW_VERTEX_FLOATS,
    ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES,
    NativePreviewBatchPayload,
    _input_texture_kind,
    build_native_preview_payloads,
)
from cdmw.rendering.native_preview_material_contract import (
    _material_hex_color_rgb,
    _native_material_hints_for_batch,
)
from cdmw.rendering.native_preview_package_writer import (
    CLOTH_RUNTIME_SCHEMA_VERSION,
    ISOLATED_PREVIEW_SCHEMA_VERSION,
    MATERIAL_CONTRACT_SCHEMA_VERSION,
    MESH_EDITOR_LOAD_TRACE_ENV,
    PREVIEW_OVERLAY_SCHEMA_VERSION,
    SUPPORTED_ISOLATED_PREVIEW_SCHEMA_VERSIONS,
    TEXTURE_QUALITY_SCHEMA_VERSION,
    _cloth_runtime_debug_metadata,
    _d3d11_material_policy_for_batch,
    _editable_value_groups_metadata,
    _editor_identity_blob,
    _mesh_editor_load_trace_enabled,
    _physics_overlays_metadata,
    _skeleton_overlay_metadata,
    _tuple3,
    _write_cloth_collider_payload,
    _write_cloth_runtime_payloads,
    _write_editor_identity_blob,
    read_isolated_d3d11_preview_manifest,
    write_isolated_d3d11_preview_package,
)

__all__ = [
    "NativePreviewBatchPayload",
    "build_native_preview_payloads",
    "ISOLATED_PREVIEW_SCHEMA_VERSION",
    "ISOLATED_PREVIEW_VERTEX_FLOATS",
    "ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES",
    "SUPPORTED_ISOLATED_PREVIEW_SCHEMA_VERSIONS",
    "read_isolated_d3d11_preview_manifest",
    "write_isolated_d3d11_preview_package",
]
