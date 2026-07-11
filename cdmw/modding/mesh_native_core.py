from __future__ import annotations

import atexit
from array import array
import ctypes
import dataclasses
import json
import math
import os
import queue
import struct
import subprocess
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence
from uuid import uuid4

if os.name == "nt":
    import msvcrt

from cdmw.core.atomic_file import atomic_publish_files
from cdmw.core.common import (
    BoundedTextTail,
    ProcessTimeoutExpired,
    finish_process_tree,
    hidden_process_group_kwargs,
    raise_if_cancelled,
    read_bounded_text_line,
    run_process_with_cancellation,
    start_bounded_text_stream_drain,
)
from cdmw.modding.mesh_deformer import MeshFaceDeleteResult, MeshPartSplitResult, _EXTRA_SUBMESH_ATTRS, recompute_submesh_normals
from cdmw.modding.mesh_native_core_blend_helpers import (
    _apply_vertex_aligned_topology_result,
    _blend_bone_assignment,
    _clear_vertex_aligned_topology_result,
    _copy_blend_bone_lists,
    _copy_blend_scalar_list,
    _copy_blend_tuple_list,
    _copy_with_blend_default,
    _edge_list,
    _int_list,
    _mirror_pairs_json,
    _tuple_value,
    _vertex_blends,
    _vertex_weights_json,
)
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.mesh_native_core_constants import (
    Face,
    NATIVE_MESH_CORE_BACKEND_ID,
    NATIVE_MESH_CORE_BINARY_NAME,
    NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR,
    Vec2,
    Vec3,
    _NATIVE_MATERIAL_REPORT_ATTRS,
    _NATIVE_MESH_EDITOR_NORMAL_OPERATIONS,
    _NATIVE_MESH_SESSION_TOKEN_ATTR,
    _NATIVE_PREVIEW_MATERIAL_OVERRIDE_KEYS,
    _TRANSIENT_NATIVE_SUBMESH_ATTRS,
)
from cdmw.modding.mesh_native_availability import (
    default_native_mesh_core_path,
    find_native_mesh_core_binary,
    native_mesh_core_available,
)
from cdmw.modding import mesh_native_core_diagnostics as _native_mesh_core_diagnostics
from cdmw.modding import mesh_native_core_temp_paths as _native_mesh_core_temp_paths
from cdmw.modding.mesh_native_core_payload_helpers import (
    _copy_vertex_aligned_list,
    _face_count_json,
    _face_json,
    _face_json_with_source_indices,
    _finite_float,
    _finite_float_sequence,
    _finite_vec2_list_or_none,
    _finite_vec3_list_or_none,
    _index,
    _iter_valid_submesh_indices,
    _native_uv_transform_payload,
    _remap_vertex_aligned_list,
    _same_vec3,
    _same_vec3_tuple,
    _sorted_unique_valid_submesh_indices,
    _source_part_adjustment_payload,
    _source_part_adjustment_pivot_vertices,
    _valid_face_triplet,
    _vec2,
    _vec2_json,
    _vec3,
    _vec3_json,
)
from cdmw.models import RunCancelled

_MESH_CORE_PROTOCOL_LINE_MAX_BYTES = 16 * 1024 * 1024
def _new_native_sparse_vertex_snapshot_id(role: str) -> str:
    return f"py-sparse-vertices-{role}-{uuid4().hex}"


from cdmw.modding.mesh_native_session_state import (
    _native_mesh_core_session_cache as _native_mesh_core_session_cache,
    _native_mesh_core_session_cache_lock as _native_mesh_core_session_cache_lock,
    _clear_native_mesh_core_session_cache as _clear_native_mesh_core_session_cache,
    _native_mesh_session_token as _native_mesh_session_token,
    _native_mesh_session_cache_key as _native_mesh_session_cache_key,
    _native_mesh_session_id as _native_mesh_session_id,
    _cached_native_mesh_session_submesh as _cached_native_mesh_session_submesh,
    _native_mesh_session_signature as _native_mesh_session_signature,
    _mark_native_mesh_session_submeshes_current as _mark_native_mesh_session_submeshes_current,
    _invalidate_native_mesh_session_submeshes as _invalidate_native_mesh_session_submeshes,
    invalidate_native_mesh_session_submeshes as invalidate_native_mesh_session_submeshes,
    _native_mesh_session_store_item as _native_mesh_session_store_item,
    _ensure_native_mesh_session_submesh as _ensure_native_mesh_session_submesh,
)


def clear_native_mesh_core_fallback_counts() -> None:
    _native_mesh_core_diagnostics.clear_native_mesh_core_fallback_counts()


def native_mesh_core_fallback_counts() -> dict[str, int]:
    return _native_mesh_core_diagnostics.native_mesh_core_fallback_counts()


def native_mesh_core_fallback_events() -> tuple[dict[str, object], ...]:
    return _native_mesh_core_diagnostics.native_mesh_core_fallback_events()


def record_native_mesh_core_fallback(operation: object, reason: object = "", **details: object) -> None:
    _native_mesh_core_diagnostics.record_native_mesh_core_fallback(operation, reason, **details)


def _native_preview_delta_output_path(suffix: str = ".bin") -> str:
    return _native_mesh_core_temp_paths.native_preview_delta_output_path(suffix)


def _native_preview_delta_output_dir() -> str:
    return _native_mesh_core_temp_paths.native_preview_delta_output_dir()


def _cleanup_native_preview_delta_paths() -> None:
    _native_mesh_core_temp_paths.cleanup_native_preview_delta_paths()


def dispose_native_mesh_history_delta(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    descriptor = value.get("before_positions_binary", value)
    if not isinstance(descriptor, Mapping):
        return False
    path = str(descriptor.get("path") or "").strip()
    return bool(path and _native_mesh_core_temp_paths.release_native_preview_delta_path(path))


def _native_mesh_core_count_hint(mesh: object, attr: str) -> int:
    try:
        value = int(getattr(mesh, attr, 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return value if value >= 0 else 0


def _native_mesh_core_service_enabled(*, stop_event: threading.Event | None = None) -> bool:
    return not os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE_SERVICE", "").strip()


from cdmw.modding.mesh_native_client import NativeMeshCoreServiceClient


_native_mesh_core_service_lock = threading.RLock()
_native_mesh_core_service: NativeMeshCoreServiceClient | None = None


def _get_native_mesh_core_service(binary: Path) -> NativeMeshCoreServiceClient:
    global _native_mesh_core_service
    with _native_mesh_core_service_lock:
        resolved_binary = Path(binary)
        binary_signature = NativeMeshCoreServiceClient.resolve_binary_signature(resolved_binary)
        if (
            _native_mesh_core_service is None
            or _native_mesh_core_service.binary != resolved_binary
            or _native_mesh_core_service.binary_signature != binary_signature
        ):
            if _native_mesh_core_service is not None:
                _native_mesh_core_service.shutdown()
            _native_mesh_core_service = NativeMeshCoreServiceClient(resolved_binary)
        return _native_mesh_core_service


def _native_mesh_core_service_running(binary: Path) -> bool:
    with _native_mesh_core_service_lock:
        service = _native_mesh_core_service
        if service is None or service.binary != Path(binary):
            return False
        process = service._process
        return process is not None and process.poll() is None


def _native_mesh_core_service_known_for_binary(binary: Path) -> bool:
    with _native_mesh_core_service_lock:
        service = _native_mesh_core_service
        return service is not None and service.binary == Path(binary)


def shutdown_native_mesh_core_service() -> None:
    global _native_mesh_core_service
    with _native_mesh_core_service_lock:
        if _native_mesh_core_service is not None:
            _native_mesh_core_service.shutdown()
            _native_mesh_core_service = None


from cdmw.modding.mesh_native_outputs import (
    write_native_preview_identity_blob as write_native_preview_identity_blob,
    _native_i32_descriptor as _native_i32_descriptor,
    _native_i32_range_descriptor as _native_i32_range_descriptor,
    write_native_preview_geometry_blob as write_native_preview_geometry_blob,
    _native_obj_submesh_payloads as _native_obj_submesh_payloads,
    export_native_obj as export_native_obj,
    write_native_obj_roundtrip_manifest as write_native_obj_roundtrip_manifest,
    build_native_fbx_geometry_arrays as build_native_fbx_geometry_arrays,
    export_native_fbx as export_native_fbx,
)


from cdmw.modding.mesh_native_preview_model import (
    _native_fbx_bone_payloads as _native_fbx_bone_payloads,
    build_native_preview_model_in_original_frame as build_native_preview_model_in_original_frame,
    _hydrate_native_preview_model_report as _hydrate_native_preview_model_report,
    _selection_domain_submesh_items as _selection_domain_submesh_items,
)


from cdmw.modding.mesh_native_transforms import (
    apply_native_mesh_transform as apply_native_mesh_transform,
    apply_native_mesh_transform_selection as apply_native_mesh_transform_selection,
    apply_native_mesh_transform_binary_selection as apply_native_mesh_transform_binary_selection,
    apply_native_mesh_sparse_vertex_restore as apply_native_mesh_sparse_vertex_restore,
)


from cdmw.modding.mesh_native_snapshot_create import (
    snapshot_native_mesh_sparse_vertex_positions as snapshot_native_mesh_sparse_vertex_positions,
    snapshot_native_mesh_submeshes as snapshot_native_mesh_submeshes,
)


from cdmw.modding.mesh_native_snapshot_restore import (
    restore_native_mesh_submesh_snapshot as restore_native_mesh_submesh_snapshot,
    _shared_native_submesh_indices as _shared_native_submesh_indices,
    restore_native_mesh_submeshes_from_mesh as restore_native_mesh_submeshes_from_mesh,
    _restore_native_submesh_snapshot_handle_sessions as _restore_native_submesh_snapshot_handle_sessions,
    _native_submesh_snapshot_handle as _native_submesh_snapshot_handle,
    _export_native_submesh_snapshot_handle as _export_native_submesh_snapshot_handle,
    dispose_native_mesh_submesh_snapshot as dispose_native_mesh_submesh_snapshot,
)


from cdmw.modding.mesh_native_snapshot_codec import (
    dispose_native_mesh_sparse_vertex_snapshot as dispose_native_mesh_sparse_vertex_snapshot,
    _mesh_snapshot_metadata as _mesh_snapshot_metadata,
    _submesh_snapshot_metadata as _submesh_snapshot_metadata,
    _snapshot_metadata_value as _snapshot_metadata_value,
    _native_submesh_snapshot_item as _native_submesh_snapshot_item,
    _copy_snapshot_descriptor as _copy_snapshot_descriptor,
    _copy_snapshot_i32_range as _copy_snapshot_i32_range,
    _copy_snapshot_i32_stride_range as _copy_snapshot_i32_stride_range,
    _submesh_from_native_snapshot_item as _submesh_from_native_snapshot_item,
    _mesh_session_item_from_native_snapshot as _mesh_session_item_from_native_snapshot,
)


from cdmw.modding.mesh_native_selection_operations import (
    apply_native_mesh_selection as apply_native_mesh_selection,
    build_native_mesh_selection_groups as build_native_mesh_selection_groups,
    select_native_mesh_uv_vertices as select_native_mesh_uv_vertices,
    summarize_native_mesh_uvs as summarize_native_mesh_uvs,
)


from cdmw.modding.mesh_native_selection import _native_selection_operation as _native_selection_operation


from cdmw.modding.mesh_native_selection import _combine_native_selection_sources as _combine_native_selection_sources


from cdmw.modding.mesh_native_selection import prune_native_mesh_selection as prune_native_mesh_selection


from cdmw.modding.mesh_native_preview_groups import (
    build_native_mesh_preview_triangle_groups as build_native_mesh_preview_triangle_groups,
    build_native_mesh_preview_vertex_update_groups as build_native_mesh_preview_vertex_update_groups,
)


from cdmw.modding.mesh_native_submesh_geometry import (
    _iter_valid_face_triples as _iter_valid_face_triples,
    _count_valid_face_triples as _count_valid_face_triples,
    summarize_native_mesh_submesh_metadata as summarize_native_mesh_submesh_metadata,
    summarize_native_mesh_selection_bounds as summarize_native_mesh_selection_bounds,
    merge_native_mesh_submeshes as merge_native_mesh_submeshes,
    decimate_native_mesh_preview_submeshes as decimate_native_mesh_preview_submeshes,
    apply_native_mesh_affine_transform_submeshes as apply_native_mesh_affine_transform_submeshes,
    clone_native_mesh_affine_transformed_submesh as clone_native_mesh_affine_transformed_submesh,
)


from cdmw.modding.mesh_native_selection_preview import (
    _native_selection_preview_group as _native_selection_preview_group,
)


from cdmw.modding.mesh_native_session_payloads import _native_mesh_editor_index_values as _native_mesh_editor_index_values


from cdmw.modding.mesh_native_session_payloads import _native_mesh_editor_index_payload as _native_mesh_editor_index_payload


from cdmw.modding.mesh_native_session_payloads import _native_mesh_editor_edge_values as _native_mesh_editor_edge_values


from cdmw.modding.mesh_native_session_payloads import _native_mesh_editor_edge_payload as _native_mesh_editor_edge_payload


from cdmw.modding.mesh_native_session_payloads import _native_mesh_editor_index_groups as _native_mesh_editor_index_groups


from cdmw.modding.mesh_native_session_payloads import _native_mesh_editor_edge_groups as _native_mesh_editor_edge_groups


from cdmw.modding.mesh_native_session_payloads import _native_mesh_editor_selection_payload as _native_mesh_editor_selection_payload


from cdmw.modding.mesh_native_session_api import native_mesh_editor_session_command as native_mesh_editor_session_command


from cdmw.modding.mesh_native_session_api import open_native_mesh_editor_session as open_native_mesh_editor_session


from cdmw.modding.mesh_native_session_api import select_native_mesh_editor_session as select_native_mesh_editor_session


from cdmw.modding.mesh_native_session_api import native_mesh_editor_session_selection_from_report as native_mesh_editor_session_selection_from_report


from cdmw.modding.mesh_native_session_api import native_mesh_editor_session_selection_groups_from_report as native_mesh_editor_session_selection_groups_from_report


from cdmw.modding.mesh_native_session_api import apply_native_mesh_editor_session as apply_native_mesh_editor_session


from cdmw.modding.mesh_native_session_api import native_mesh_editor_source_normals_payload as native_mesh_editor_source_normals_payload


from cdmw.modding.mesh_native_session_api import _apply_native_material_report_attrs as _apply_native_material_report_attrs


from cdmw.modding.mesh_native_session_api import _apply_native_material_edit_report as _apply_native_material_edit_report


from cdmw.modding.mesh_native_session_api import native_mesh_editor_session_preview_triangle_groups as native_mesh_editor_session_preview_triangle_groups


from cdmw.modding.mesh_native_session_api import native_mesh_editor_session_preview_vertex_update_groups as native_mesh_editor_session_preview_vertex_update_groups


from cdmw.modding.mesh_native_session_api import _native_preview_triangle_group_with_report_material as _native_preview_triangle_group_with_report_material


from cdmw.modding.mesh_native_session_api import _reconcile_native_editor_submesh_count as _reconcile_native_editor_submesh_count


from cdmw.modding.mesh_native_session_api import summarize_native_mesh_editor_session as summarize_native_mesh_editor_session


from cdmw.modding.mesh_native_session_api import undo_native_mesh_editor_session as undo_native_mesh_editor_session


from cdmw.modding.mesh_native_session_api import redo_native_mesh_editor_session as redo_native_mesh_editor_session


from cdmw.modding.mesh_native_session_api import export_native_mesh_editor_session_snapshot as export_native_mesh_editor_session_snapshot


from cdmw.modding.mesh_native_session_api import export_native_mesh_editor_session_to_mesh as export_native_mesh_editor_session_to_mesh


from cdmw.modding.mesh_native_session_api import close_native_mesh_editor_session as close_native_mesh_editor_session


from cdmw.modding.mesh_native_morph import (
    apply_native_morph_slider_values as apply_native_morph_slider_values,
    build_native_morph_post_edit_deltas as build_native_morph_post_edit_deltas,
    build_native_morph_target_delta as build_native_morph_target_delta,
    build_native_static_donor_indices as build_native_static_donor_indices,
)


from cdmw.modding.mesh_native_rigging import (
    _apply_native_skin_weight_report as _apply_native_skin_weight_report,
    _native_pose_preview_bones_payload as _native_pose_preview_bones_payload,
    _native_pose_preview_matrix_payload as _native_pose_preview_matrix_payload,
    _native_pose_preview_rotations_payload as _native_pose_preview_rotations_payload,
    apply_native_mesh_pose_preview as apply_native_mesh_pose_preview,
    write_native_pose_preview_geometry_blob as write_native_pose_preview_geometry_blob,
    apply_native_mesh_skin_weights as apply_native_mesh_skin_weights,
    transfer_native_mesh_skin_weights_from_source as transfer_native_mesh_skin_weights_from_source,
    build_native_region_volume_delta as build_native_region_volume_delta,
)


from cdmw.modding.mesh_native_brush import (
    _vertex_weights_binary_payloads as _vertex_weights_binary_payloads,
    _native_brush_edit_payload as _native_brush_edit_payload,
    apply_native_mesh_brush as apply_native_mesh_brush,
    apply_native_mesh_brush_binary_selection as apply_native_mesh_brush_binary_selection,
    apply_native_mesh_brush_selection as apply_native_mesh_brush_selection,
)


from cdmw.modding.mesh_native_topology_basic import (
    _mesh_edit_removed_count as _mesh_edit_removed_count,
    apply_native_mesh_delete as apply_native_mesh_delete,
    apply_native_mesh_dissolve as apply_native_mesh_dissolve,
    apply_native_mesh_extrude as apply_native_mesh_extrude,
    apply_native_mesh_inset as apply_native_mesh_inset,
    apply_native_mesh_compact_orphans as apply_native_mesh_compact_orphans,
    apply_native_mesh_fix_winding as apply_native_mesh_fix_winding,
    apply_native_mesh_fill_holes as apply_native_mesh_fill_holes,
    apply_native_mesh_fill as apply_native_mesh_fill,
    apply_native_mesh_edge_split as apply_native_mesh_edge_split,
)


from cdmw.modding.mesh_native_topology_selection import (
    _native_loop_cut_edit as _native_loop_cut_edit,
    apply_native_mesh_loop_cut as apply_native_mesh_loop_cut,
    apply_native_mesh_merge as apply_native_mesh_merge,
    apply_native_mesh_weld as apply_native_mesh_weld,
    _display_face_json as _display_face_json,
    apply_native_mesh_triangulate_display as apply_native_mesh_triangulate_display,
)


from cdmw.modding.mesh_native_duplicate_reports import (
    _append_native_duplicate_report_submeshes as _append_native_duplicate_report_submeshes,
)


from cdmw.modding.mesh_native_topology_parts import (
    apply_native_mesh_duplicate as apply_native_mesh_duplicate,
    apply_native_mesh_mirror as apply_native_mesh_mirror,
    apply_native_mesh_separate as apply_native_mesh_separate,
    apply_native_mesh_bridge as apply_native_mesh_bridge,
    apply_native_mesh_split as apply_native_mesh_split,
    apply_native_mesh_subdivide as apply_native_mesh_subdivide,
)


from cdmw.modding.mesh_native_normals import (
    _allow_python_normal_recompute_fallback as _allow_python_normal_recompute_fallback,
    _recompute_normals_native_or_fallback as _recompute_normals_native_or_fallback,
    apply_native_mesh_copy_normals as apply_native_mesh_copy_normals,
    apply_native_mesh_recalculate_normals as apply_native_mesh_recalculate_normals,
    apply_native_mesh_weighted_normals as apply_native_mesh_weighted_normals,
    apply_native_mesh_flip_normals as apply_native_mesh_flip_normals,
    apply_native_mesh_sharpen_normals as apply_native_mesh_sharpen_normals,
    _apply_native_mesh_normal_edit as _apply_native_mesh_normal_edit,
    apply_native_mesh_generate_tangents as apply_native_mesh_generate_tangents,
    apply_native_mesh_remove_doubles as apply_native_mesh_remove_doubles,
)


from cdmw.modding.mesh_native_uv import (
    native_mesh_auto_uv_report as native_mesh_auto_uv_report,
    native_scene_import_report as native_scene_import_report,
    native_mesh_optimization_report as native_mesh_optimization_report,
    apply_native_mesh_auto_uv as apply_native_mesh_auto_uv,
    apply_native_mesh_uv_transform as apply_native_mesh_uv_transform,
    apply_native_mesh_uv_transform_submeshes as apply_native_mesh_uv_transform_submeshes,
    apply_native_mesh_uv_atlas_submesh as apply_native_mesh_uv_atlas_submesh,
)


from cdmw.modding.mesh_native_topology_payloads import _topology_edit_submeshes as _topology_edit_submeshes


from cdmw.modding.mesh_native_report_edits import _apply_mesh_edit_report as _apply_mesh_edit_report


from cdmw.modding.mesh_native_report_application import _refresh_mesh_totals as _refresh_mesh_totals


from cdmw.modding.mesh_native_report_application import _apply_transform_report as _apply_transform_report


from cdmw.modding.mesh_native_report_application import _native_report_metrics as _native_report_metrics


from cdmw.modding.mesh_native_report_application import _apply_selection_report as _apply_selection_report


from cdmw.modding.mesh_native_report_application import _apply_recalculate_normals_report as _apply_recalculate_normals_report


from cdmw.modding.mesh_native_report_application import _apply_generate_tangents_report as _apply_generate_tangents_report


from cdmw.modding.mesh_native_report_application import _report_count as _report_count


from cdmw.modding.mesh_native_report_application import _apply_native_tangent_split_result as _apply_native_tangent_split_result


from cdmw.modding.mesh_native_report_application import _tangent_face_corner_report as _tangent_face_corner_report


from cdmw.modding.mesh_native_report_application import _apply_face_corner_tangent_split as _apply_face_corner_tangent_split


from cdmw.modding.mesh_native_report_application import _parsed_face_corner_tangents as _parsed_face_corner_tangents


from cdmw.modding.mesh_native_report_application import _valid_face_tuple as _valid_face_tuple


from cdmw.modding.mesh_native_report_geometry import _apply_cleanup_report as _apply_cleanup_report


from cdmw.modding.mesh_native_report_geometry import _apply_auto_uv_report as _apply_auto_uv_report


from cdmw.modding.mesh_native_report_geometry import _apply_uv_transform_report as _apply_uv_transform_report


from cdmw.modding.mesh_native_report_application import _merge_changed_vertices as _merge_changed_vertices


from cdmw.modding.mesh_native_dispatch import (
    _native_job_kwargs as _native_job_kwargs,
    _run_native_mesh_core_service_job as _run_native_mesh_core_service_job,
    _run_native_mesh_core_service_inline_job as _run_native_mesh_core_service_inline_job,
    _run_native_mesh_core_job as _run_native_mesh_core_job,
)


from cdmw.modding.mesh_native_preview_payloads import (
    _changed_vertex_range,
    _changed_vertices_binary_descriptor,
    _contiguous_vertex_range,
    _copy_vertex_indices_from_report_item,
    _iter_valid_changed_vertex_indices,
    _native_preview_triangle_group,
    _native_preview_vertex_update_group,
    _vertex_blends_from_report_item,
)


from cdmw.modding.mesh_native_history import (
    _bounded_changed_vertices,
    _changed_vertices_for_report,
    _changed_vertices_from_report_item,
    _native_history_delta_vertex_payload,
    _native_history_vertex_delta,
    _native_history_vertex_payload,
    _vertex_indices_from_history_descriptor,
    native_mesh_history_delta_positions,
)


from cdmw.modding.mesh_native_payloads import (
    _contiguous_i32_range,
    _contiguous_i32_stride_range,
    _i32_range_report_values,
    _i32_stride_range_report_values,
    _is_identity_i32_sequence,
    _put_i32_range_or_binary_payload,
    _put_selected_edit_domain_payload,
    _put_selected_vertices_payload,
    _put_source_face_indices_json_payload,
    _put_source_face_indices_payload,
    _put_source_vertex_indices_payload,
    _put_source_vertex_map_payload,
    _put_source_vertex_offsets_payload,
    _put_vertex_indices_payload,
    _selected_edge_values,
    _selected_face_values,
    _selected_vertex_values,
    _source_vertex_map_report_values,
    _source_vertex_offsets_report_values,
)


from cdmw.modding.mesh_native_binary_io import (
    _native_binary_descriptor,
    _native_existing_binary_descriptor,
    _read_bone_binary_report_payloads,
    _read_f64_binary_report_payload,
    _read_face_binary_report_payload,
    _read_i32_binary_report_payload,
    _read_i32_components_binary_report_payload,
    _read_int_binary_report_payload,
    _read_vec2_binary_report_payload,
    _read_vec3_binary_payload,
    _read_vec3_binary_report_payload,
    _write_bone_binary_payloads,
    _write_edge_binary_payload,
    _write_f64_binary_payload,
    _write_face_binary_payload,
    _write_face_binary_payload_with_source_indices,
    _write_int_binary_payload,
    _write_vec2_binary_payload,
    _write_vec3_binary_payload,
)


atexit.register(shutdown_native_mesh_core_service)
atexit.register(_cleanup_native_preview_delta_paths)


__all__ = [
    "NATIVE_MESH_CORE_BACKEND_ID",
    "NATIVE_MESH_CORE_BINARY_NAME",
    "apply_native_mesh_auto_uv",
    "apply_native_mesh_affine_transform_submeshes",
    "apply_native_mesh_editor_session",
    "apply_native_mesh_bridge",
    "apply_native_mesh_brush",
    "apply_native_mesh_brush_binary_selection",
    "apply_native_mesh_brush_selection",
    "apply_native_mesh_compact_orphans",
    "apply_native_mesh_copy_normals",
    "apply_native_mesh_delete",
    "apply_native_mesh_dissolve",
    "apply_native_mesh_duplicate",
    "apply_native_mesh_edge_split",
    "apply_native_mesh_extrude",
    "apply_native_mesh_fill",
    "apply_native_mesh_fill_holes",
    "apply_native_mesh_fix_winding",
    "apply_native_mesh_generate_tangents",
    "apply_native_mesh_flip_normals",
    "apply_native_mesh_inset",
    "apply_native_mesh_loop_cut",
    "apply_native_mesh_merge",
    "apply_native_mesh_mirror",
    "apply_native_morph_slider_values",
    "apply_native_mesh_pose_preview",
    "apply_native_mesh_recalculate_normals",
    "apply_native_mesh_remove_doubles",
    "apply_native_mesh_selection",
    "apply_native_mesh_separate",
    "apply_native_mesh_sharpen_normals",
    "apply_native_mesh_skin_weights",
    "apply_native_mesh_sparse_vertex_restore",
    "apply_native_mesh_split",
    "apply_native_mesh_subdivide",
    "apply_native_mesh_transform",
    "apply_native_mesh_transform_binary_selection",
    "apply_native_mesh_transform_selection",
    "apply_native_mesh_triangulate_display",
    "apply_native_mesh_uv_atlas_submesh",
    "apply_native_mesh_uv_transform",
    "apply_native_mesh_uv_transform_submeshes",
    "apply_native_mesh_weld",
    "apply_native_mesh_weighted_normals",
    "build_native_preview_model_in_original_frame",
    "build_native_fbx_geometry_arrays",
    "build_native_mesh_preview_triangle_groups",
    "build_native_mesh_preview_vertex_update_groups",
    "build_native_morph_post_edit_deltas",
    "build_native_morph_target_delta",
    "build_native_region_volume_delta",
    "build_native_static_donor_indices",
    "build_native_mesh_selection_groups",
    "close_native_mesh_editor_session",
    "decimate_native_mesh_preview_submeshes",
    "default_native_mesh_core_path",
    "dispose_native_mesh_history_delta",
    "dispose_native_mesh_sparse_vertex_snapshot",
    "dispose_native_mesh_submesh_snapshot",
    "export_native_fbx",
    "export_native_mesh_editor_session_to_mesh",
    "export_native_mesh_editor_session_snapshot",
    "export_native_obj",
    "find_native_mesh_core_binary",
    "invalidate_native_mesh_session_submeshes",
    "merge_native_mesh_submeshes",
    "native_mesh_auto_uv_report",
    "native_mesh_core_available",
    "native_mesh_editor_source_normals_payload",
    "native_mesh_editor_session_command",
    "native_mesh_editor_session_preview_triangle_groups",
    "native_mesh_editor_session_preview_vertex_update_groups",
    "native_mesh_editor_session_selection_from_report",
    "native_mesh_editor_session_selection_groups_from_report",
    "native_mesh_optimization_report",
    "native_mesh_history_delta_positions",
    "native_scene_import_report",
    "prune_native_mesh_selection",
    "restore_native_mesh_submeshes_from_mesh",
    "restore_native_mesh_submesh_snapshot",
    "open_native_mesh_editor_session",
    "redo_native_mesh_editor_session",
    "select_native_mesh_uv_vertices",
    "select_native_mesh_editor_session",
    "snapshot_native_mesh_submeshes",
    "snapshot_native_mesh_sparse_vertex_positions",
    "summarize_native_mesh_selection_bounds",
    "summarize_native_mesh_editor_session",
    "summarize_native_mesh_submesh_metadata",
    "summarize_native_mesh_uvs",
    "transfer_native_mesh_skin_weights_from_source",
    "undo_native_mesh_editor_session",
    "write_native_pose_preview_geometry_blob",
    "write_native_preview_geometry_blob",
    "write_native_preview_identity_blob",
    "write_native_obj_roundtrip_manifest",
]
