"""Scene-file import helpers for static mesh replacement.

OBJ remains the strict round-trip format.  This module accepts broader scene
formats only for static replacement and normalizes them into ParsedMesh.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import mimetypes
import re
import struct
import tempfile
import xml.etree.ElementTree as ET
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import unquote, urlparse

from .logging import get_logger
from .mesh_importer import import_obj
from .mesh_parser import ParsedMesh, SubMesh, _compute_smooth_normals, parse_mesh
from cdmw.models import PreviewMaterialParameterInput, PreviewMaterialTextureInput
from .scene_geometry_utils import _bbox, _dedupe_text, _safe_int
from .scene_geometry_utils import _copy_submesh_with_transform
from .scene_gltf_import import (
    _GLTF_COMPONENT_FORMATS,
    _GLTF_IMAGE_MIME_EXTENSIONS,
    _GLTF_TYPE_COUNTS,
    _GltfMeshInstance,
    _GltfPayload,
    _apply_gltf_preview_material_metadata,
    _attach_gltf_vertex_color_summary,
    _bake_gltf_skin_primitive,
    _compose_trs_matrix,
    _decode_data_uri,
    _decode_data_uri_with_mime,
    _embedded_gltf_extract_dir,
    _gltf_buffer_view,
    _gltf_inverse_bind_matrices,
    _gltf_mat4_to_row_major,
    _gltf_material_info,
    _gltf_material_texcoord_index,
    _gltf_node_matrix,
    _gltf_node_world_matrices,
    _gltf_scene_material_slot,
    _gltf_skin_joint_matrices,
    _gltf_texture_image_path,
    _gltf_texture_info_parameters,
    _gltf_texture_info_texcoord,
    _gltf_texture_transform,
    _iter_gltf_mesh_instances,
    _load_gltf_payload,
    _normalize_gltf_component,
    _parse_gltf_primitive,
    _read_glb,
    _read_gltf_accessor,
    _read_gltf_buffer_view_bytes,
    _read_gltf_vertex_colors,
    _resolve_gltf_image,
    _validate_gltf_static_payload,
    _walk_gltf_node,
    _write_embedded_gltf_image,
    import_gltf,
)
from .scene_collada_import import (
    _ColladaGeometry,
    _collada_corner_index,
    _collada_image_paths,
    _collada_material_names,
    _collada_material_parameters,
    _collada_material_texture_slots,
    _collada_node_matrix,
    _collada_sources,
    _collada_vertices_sources,
    _guess_scene_material_texture,
    _iter_collada_geometry_instances,
    _parse_collada_geometry,
    _parse_collada_primitive,
    _resolve_collada_image_reference,
    _source_tuple,
    import_dae,
)
from .scene_geometry_utils import _dedupe_paths
from .scene_material_audit import (
    _apply_scene_material_parameters_to_submesh,
    _apply_scene_material_slots_to_submesh,
    _scene_parameter_color,
    _scene_parameter_numeric,
)
from .scene_geometry_utils import (
    _float_list,
    _identity_matrix,
    _invert_affine_matrix,
    _multiply_matrix,
    _normalize_vec,
    _parse_float_list,
    _resolve_scene_uri,
    _transform_point,
    _transform_vector,
)
from .scene_material_audit import (
    ExternalMaterialClassEvidence,
    ExternalMaterialInventory,
    ExternalMaterialSectionInventory,
    ExternalMaterialTextureInventory,
    ExternalModelAudit,
    ImportedMaterialBinding,
    SceneMaterialTextureSlot,
    _MATERIAL_CLASS_TEXTURE_ROLE_TOKENS,
    _SCENE_SLOT_PARAMETER_NAMES,
    _SCENE_TEXTURE_FACT_CHANNEL_STATS_MAX_PIXELS,
    _aggregate_external_material_classes,
    _append_scene_parameter,
    _audit_texture_slot_from_path,
    _build_external_material_inventory,
    _channel_stats_evidence,
    _classify_external_material,
    _external_inventory_alpha_mode,
    _external_inventory_color_factor,
    _external_inventory_emissive_color,
    _external_inventory_scalar_hints,
    _external_inventory_texture_slots,
    _external_inventory_vertex_alpha,
    _external_inventory_vertex_color_factor,
    _external_inventory_warnings,
    _external_inventory_workflow_from_slots,
    _external_material_inventory_from_binding_group,
    _external_material_inventory_from_submesh_group,
    _external_material_section_inventory,
    _external_slot_color_space,
    _external_texture_input_source,
    _external_texture_input_texcoord,
    _external_texture_input_uv_transform,
    _external_texture_inventory_from_input,
    _external_texture_inventory_from_path,
    _hex_color_to_rgb,
    _material_class_texture_token_text,
    _mesh_extent,
    _normalize_external_pbr_workflow,
    _normalized_material_scalar_name,
    _result_with_external_audit,
    _safe_float_or_none,
    _scene_material_slot,
    _scene_preview_color_parameter,
    _scene_preview_float_parameter,
    _scene_preview_string_parameter,
    _scene_slot_semantics,
    _texture_image_facts,
    _texture_resolution,
    _visible_texture_score,
    audit_external_model,
)

logger = get_logger("core.scene_importer")

from .scene_texture_discovery import (
    LOCAL_ARCHIVE_MESH_IMPORT_EXTENSIONS,
    SCENE_COMPANION_SOURCE_EXTENSIONS,
    SCENE_SIDECAR_SOURCE_EXTENSIONS,
    SCENE_TEXTURE_DIAGNOSTIC_ONLY_EXTENSIONS,
    SCENE_TEXTURE_SOURCE_EXTENSIONS,
    _attach_fallback_texture_references,
    _attach_sibling_material_texture_slots,
    _discover_local_mesh_companion_files,
    _discover_local_mesh_sidecars,
    _discover_material_named_texture_files,
    _discover_nearby_scene_texture_files,
    _find_first_local_file_by_basename,
    _local_package_root,
    _local_sidecar_texture_references,
    _nearby_scene_texture_roots,
    _obj_map_reference_from_parts,
    _obj_material_library_paths,
    _obj_material_parameters,
    _obj_material_texture_paths,
    _obj_material_texture_references,
    _obj_material_texture_slots,
    _read_local_sidecar_text,
    _resolve_local_texture_reference,
    _resolve_scene_texture_path_reference,
    _scene_texture_candidate_priority,
    _scene_texture_fallback_slot_kind,
    _scene_texture_group_key,
    _scene_texture_search_roots,
    discover_local_mesh_supplemental_files,
    discover_scene_texture_files,
)

SCENE_IMPORT_EXTENSIONS = {".obj", ".dae", ".gltf", ".glb", ".zip"} | LOCAL_ARCHIVE_MESH_IMPORT_EXTENSIONS


from .scene_import_result_ops import (
    SceneImportResult,
    SceneMeshAppendResult,
    SceneMeshQualityReductionReport,
    _decimate_submesh_for_import_quality,
    _scene_result_context,
    append_scene_import_to_mesh,
    flatten_scene_import_result_parts,
    group_scene_import_result_parts_by_material,
    reduce_scene_import_result_quality,
    refresh_parsed_mesh_totals,
)


def import_scene_mesh(path: str | Path) -> ParsedMesh:
    return import_scene_mesh_with_report(path).mesh


def import_scene_mesh_with_report(path: str | Path, *, include_external_audit: bool = True) -> SceneImportResult:
    source_path = Path(path).expanduser().resolve()
    suffix = source_path.suffix.lower()
    if suffix == ".zip":
        from cdmw.core.model_catalogue import resolve_importable_model_path, zip_importable_members

        members = zip_importable_members(source_path)
        resolved_path = resolve_importable_model_path(source_path)
        if resolved_path is None:
            raise ValueError(
                f"ZIP file does not contain an importable model: {source_path}. "
                "Expected OBJ, DAE, glTF, GLB, PAC, PAM, or PAMLOD."
            )
        result = import_scene_mesh_with_report(resolved_path, include_external_audit=include_external_audit)
        member_label = members[0] if members else resolved_path.name
        result.diagnostics = (
            f"Resolved ZIP archive {source_path.name} to {member_label}.",
        ) + tuple(result.diagnostics or ())
        return result
    if suffix == ".obj":
        mesh = import_obj(str(source_path))
        if not str(getattr(mesh, "format", "") or "").strip():
            mesh.format = "obj"
        if not str(getattr(mesh, "path", "") or "").strip():
            mesh.path = source_path.as_posix()
        material_slots = _obj_material_texture_slots(source_path)
        material_parameters = _obj_material_parameters(source_path)
        material_slots_by_lower = {str(name or "").strip().lower(): slots for name, slots in material_slots.items()}
        material_parameters_by_lower = {str(name or "").strip().lower(): parameters for name, parameters in material_parameters.items()}
        for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
            material_key = str(getattr(submesh, "material", "") or "").strip()
            slots = material_slots.get(material_key) or material_slots_by_lower.get(material_key.lower()) or ()
            parameters = material_parameters.get(material_key) or material_parameters_by_lower.get(material_key.lower()) or ()
            if slots or parameters:
                _apply_scene_material_slots_to_submesh(submesh, slots, material_parameters=parameters, confidence="obj_mtl")
        discovered_textures = discover_scene_texture_files(source_path, mesh)
        _attach_fallback_texture_references(mesh, discovered_textures)
        attached_slots = _attach_sibling_material_texture_slots(mesh, discovered_textures)
        diagnostics = (
            (f"Attached {attached_slots:,} sibling OBJ texture support slot(s) by filename fallback.",)
            if attached_slots
            else ()
        )
        return _result_with_external_audit(
            source_path,
            SceneImportResult(mesh=mesh, diagnostics=diagnostics, discovered_texture_files=discovered_textures),
            enabled=include_external_audit,
        )
    if suffix == ".dae":
        mesh = import_dae(source_path)
        discovered_textures = discover_scene_texture_files(source_path, mesh)
        attached_slots = _attach_sibling_material_texture_slots(mesh, discovered_textures)
        diagnostics = (
            (f"Attached {attached_slots:,} sibling DAE texture support slot(s) by filename fallback.",)
            if attached_slots
            else ()
        )
        return _result_with_external_audit(
            source_path,
            SceneImportResult(mesh=mesh, diagnostics=diagnostics, discovered_texture_files=discovered_textures),
            enabled=include_external_audit,
        )
    if suffix in {".gltf", ".glb"}:
        return import_gltf(source_path, include_external_audit=include_external_audit)
    if suffix in LOCAL_ARCHIVE_MESH_IMPORT_EXTENSIONS:
        mesh = parse_mesh(source_path.read_bytes(), source_path.as_posix())
        if not mesh.submeshes or mesh.total_faces <= 0:
            raise ValueError(f"{source_path.suffix.upper().lstrip('.')} source did not contain recoverable mesh geometry: {source_path}")
        discovered_files = discover_local_mesh_supplemental_files(source_path, mesh)
        discovered_textures = tuple(path for path in discovered_files if path.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS)
        discovered_supplemental = tuple(
            path
            for path in discovered_files
            if path.suffix.lower() in SCENE_SIDECAR_SOURCE_EXTENSIONS
            or path.suffix.lower() in SCENE_COMPANION_SOURCE_EXTENSIONS
        )
        discovered_sidecars = tuple(path for path in discovered_supplemental if path.suffix.lower() in SCENE_SIDECAR_SOURCE_EXTENSIONS)
        discovered_companions = tuple(
            path for path in discovered_supplemental if path.suffix.lower() in SCENE_COMPANION_SOURCE_EXTENSIONS
        )
        diagnostics = [
            f"Parsed local {source_path.suffix.upper().lstrip('.')} mesh source for Mesh Replacement.",
        ]
        if mesh.has_bones:
            diagnostics.append(
                "Source bone weights were detected; Mesh Replacement uses the selected target's donor skeleton/layout."
            )
        if discovered_sidecars:
            diagnostics.append(f"Discovered {len(discovered_sidecars):,} local material sidecar file(s).")
        if discovered_companions:
            diagnostics.append(f"Discovered {len(discovered_companions):,} local Crimson companion metadata file(s).")
        if discovered_textures:
            diagnostics.append(f"Discovered {len(discovered_textures):,} local DDS/texture file(s).")
        return _result_with_external_audit(
            source_path,
            SceneImportResult(
                mesh=mesh,
                diagnostics=tuple(diagnostics),
                discovered_texture_files=discovered_textures,
                discovered_supplemental_files=discovered_supplemental,
            ),
            enabled=include_external_audit,
        )
    if suffix in {".fbx", ".blend", ".usd", ".usda", ".usdc", ".usdz"}:
        raise ValueError(
            f"{source_path.suffix.upper().lstrip('.')} files are browsable but not preview-importable in this build. "
            "Export OBJ, DAE, GLB, or glTF to keep material/texture preview support without external converter dependencies."
        )
    raise ValueError(f"Unsupported mesh import format: {source_path.suffix or source_path.name}")


def import_fbx(path: str | Path) -> ParsedMesh:
    fbx_path = Path(path).expanduser().resolve()
    raise ValueError(
        f"FBX import is disabled in this build because it required launching Blender: {fbx_path}. "
        "Export the model as OBJ or DAE first."
    )
