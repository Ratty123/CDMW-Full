from __future__ import annotations

from importlib import import_module
import os
from pathlib import Path
import tempfile
import threading
from typing import Iterable, Mapping, Sequence

from cdmw.modding.mesh_native_binary_io import _read_i32_components_binary_report_payload, _read_int_binary_report_payload, _write_vec3_binary_payload
from cdmw.modding.mesh_native_core_blend_helpers import _edge_list, _int_list
from cdmw.modding.mesh_native_core_constants import NATIVE_MESH_CORE_BACKEND_ID, _NATIVE_MATERIAL_REPORT_ATTRS, _NATIVE_PREVIEW_MATERIAL_OVERRIDE_KEYS
from cdmw.modding.mesh_native_core_payload_helpers import _index, _sorted_unique_valid_submesh_indices
from cdmw.modding.mesh_native_duplicate_reports import _append_native_duplicate_report_submeshes
from cdmw.modding.mesh_native_payloads import _i32_range_report_values
from cdmw.modding.mesh_native_preview_payloads import _native_preview_triangle_group, _native_preview_vertex_update_group
from cdmw.modding.mesh_native_report_application import _refresh_mesh_totals
from cdmw.modding.mesh_native_report_edits import _apply_mesh_edit_report
from cdmw.modding.mesh_native_session_payloads import _native_mesh_editor_selection_payload
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh


def _facade_attr(name: str):
    return getattr(import_module("cdmw.modding.mesh_native_core"), name)


def _cached_native_mesh_session_submesh(*args, **kwargs):
    return _facade_attr("_cached_native_mesh_session_submesh")(*args, **kwargs)


def _mesh_snapshot_metadata(*args, **kwargs):
    return _facade_attr("_mesh_snapshot_metadata")(*args, **kwargs)


def _native_mesh_core_service_enabled(*args, **kwargs):
    return _facade_attr("_native_mesh_core_service_enabled")(*args, **kwargs)


def _native_mesh_session_store_item(*args, **kwargs):
    return _facade_attr("_native_mesh_session_store_item")(*args, **kwargs)


def _native_preview_delta_output_dir() -> str:
    return _facade_attr("_native_preview_delta_output_dir")()


def _native_preview_delta_output_path(suffix: str = ".bin") -> str:
    return _facade_attr("_native_preview_delta_output_path")(suffix)


def _native_selection_preview_group(*args, **kwargs):
    return _facade_attr("_native_selection_preview_group")(*args, **kwargs)


def _native_submesh_snapshot_item(*args, **kwargs):
    return _facade_attr("_native_submesh_snapshot_item")(*args, **kwargs)


def _run_native_mesh_core_service_job(*args, **kwargs):
    return _facade_attr("_run_native_mesh_core_service_job")(*args, **kwargs)


def _snapshot_metadata_value(value: object):
    return _facade_attr("_snapshot_metadata_value")(value)


def _submesh_snapshot_metadata(*args, **kwargs):
    return _facade_attr("_submesh_snapshot_metadata")(*args, **kwargs)


def find_native_mesh_core_binary():
    return _facade_attr("find_native_mesh_core_binary")()


def restore_native_mesh_submesh_snapshot(*args, **kwargs):
    return _facade_attr("restore_native_mesh_submesh_snapshot")(*args, **kwargs)


def native_mesh_editor_session_command(
    command: str,
    session_id: str,
    payload: Mapping[str, object] | None = None,
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None or not _native_mesh_core_service_enabled(stop_event=stop_event):
        return None
    session_text = str(session_id or "").strip()
    command_text = str(command or "").strip().lower()
    if not session_text or not command_text:
        return None
    request: dict[str, object] = dict(payload or {})
    request.update(
        {
            "version": 1,
            "backend": NATIVE_MESH_CORE_BACKEND_ID,
            "protocol": "mesh-editor-session-json",
            "command": command_text,
            "session_id": session_text,
        }
    )
    return _run_native_mesh_core_service_job(
        binary,
        "mesh-editor-session-json",
        request,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )


def open_native_mesh_editor_session(
    mesh: ParsedMesh,
    session_id: str,
    *,
    submesh_indices: object = None,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, object] | None:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return None
    binary = find_native_mesh_core_binary()
    if binary is None or not _native_mesh_core_service_enabled(stop_event=stop_event):
        return None
    indices = _sorted_unique_valid_submesh_indices(mesh, submesh_indices, all_when_none=True)
    if not indices:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="cdmw_mesh_editor_session_") as sidecar_root_raw:
            sidecar_root = Path(sidecar_root_raw)
            items: list[dict[str, object]] = []
            for submesh_index in indices:
                cached_session_id = _cached_native_mesh_session_submesh(mesh, submesh_index)
                item = {"index": submesh_index, "session_id": cached_session_id} if cached_session_id else None
                if item is None:
                    item = _native_mesh_session_store_item(
                        mesh.submeshes[submesh_index],
                        submesh_index,
                        sidecar_root / f"editor_{submesh_index}",
                    )
                if item is not None:
                    items.append(item)
            if not items:
                return None
            return _run_native_mesh_core_service_job(
                binary,
                "mesh-editor-session-json",
                {
                    "version": 1,
                    "backend": NATIVE_MESH_CORE_BACKEND_ID,
                    "protocol": "mesh-editor-session-json",
                    "command": "open",
                    "session_id": str(session_id or "").strip(),
                    "submeshes": items,
                },
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None


def select_native_mesh_editor_session(
    session_id: str,
    selection: Mapping[str, object],
    *,
    operation: object = "replace",
    iterations: object = 1,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 2.0,
) -> dict[str, object] | None:
    try:
        with tempfile.TemporaryDirectory(prefix="cdmw_mesh_editor_selection_") as sidecar_root_raw:
            sidecar_root = Path(sidecar_root_raw)
            payload: dict[str, object] = {
                "selection": _native_mesh_editor_selection_payload(selection, sidecar_root),
                "selection_operation": str(operation or "replace").strip().lower() or "replace",
                "selection_output_dir": _native_preview_delta_output_dir(),
            }
            selected_iterations = _index(iterations)
            if selected_iterations is not None:
                payload["iterations"] = max(0, selected_iterations)
            return native_mesh_editor_session_command(
                "select",
                session_id,
                payload,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None


def native_mesh_editor_session_selection_from_report(report: Mapping[str, object]) -> dict[str, object] | None:
    raw_items = report.get("submeshes")
    if not isinstance(raw_items, list):
        return None
    max_index = 2_147_483_647
    vertices: dict[int, set[int]] = {}
    edges: dict[int, set[tuple[int, int]]] = {}
    faces: dict[int, set[int]] = {}
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            continue
        submesh_index = _index(raw_item.get("index"))
        if submesh_index is None or submesh_index < 0:
            continue
        selected_vertices = _i32_range_report_values(
            raw_item,
            start_key="selected_vertex_start",
            count_key="selected_vertex_count",
            max_count=max_index,
        )
        if selected_vertices is None:
            selected_vertices = _read_int_binary_report_payload(raw_item.get("selected_vertices_binary"), max_count=max_index)
        if selected_vertices is None:
            selected_vertices = [index for index in _int_list(raw_item.get("selected_vertices")) if 0 <= index < max_index]
        if selected_vertices:
            vertices[submesh_index] = set(selected_vertices)

        edge_count = _index((raw_item.get("selected_edges_binary") or {}).get("count")) if isinstance(raw_item.get("selected_edges_binary"), Mapping) else None
        raw_edges = (
            _read_i32_components_binary_report_payload(raw_item.get("selected_edges_binary"), expected_count=edge_count, components=2)
            if edge_count is not None
            else None
        )
        selected_edges = {
            (min(left, right), max(left, right))
            for left, right in (raw_edges if raw_edges is not None else _edge_list(raw_item.get("selected_edges")))
            if 0 <= left < max_index and 0 <= right < max_index and left != right
        }
        if selected_edges:
            edges[submesh_index] = selected_edges

        selected_faces = _i32_range_report_values(
            raw_item,
            start_key="selected_face_start",
            count_key="selected_face_count",
            max_count=max_index,
        )
        if selected_faces is None:
            selected_faces = _read_int_binary_report_payload(raw_item.get("selected_faces_binary"), max_count=max_index)
        if selected_faces is None:
            selected_faces = [index for index in _int_list(raw_item.get("selected_faces")) if 0 <= index < max_index]
        if selected_faces:
            faces[submesh_index] = set(selected_faces)
    return {
        "vertices_by_submesh": vertices,
        "edges_by_submesh": edges,
        "faces_by_submesh": faces,
        "source_indices": tuple(index for index in _int_list(report.get("source_indices")) if index >= 0),
    }


def native_mesh_editor_session_selection_groups_from_report(report: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    raw_groups = report.get("selection_groups")
    if not isinstance(raw_groups, list):
        raw_groups = report.get("groups")
    if not isinstance(raw_groups, list):
        return ()
    groups: list[Mapping[str, object]] = []
    for raw_group in raw_groups:
        if not isinstance(raw_group, Mapping):
            continue
        submesh_index = _index(raw_group.get("source_submesh_index"))
        if submesh_index is None or submesh_index < 0:
            continue
        group = _native_selection_preview_group(raw_group, submesh_index)
        if group is not None:
            groups.append(group)
    return tuple(groups)


def apply_native_mesh_editor_session(
    session_id: str,
    edit: Mapping[str, object],
    *,
    selection: Mapping[str, object] | None = None,
    capture_deltas: bool = True,
    include_preview_deltas: bool = True,
    binary_preview_deltas: bool = False,
    stroke_phase: str | None = None,
    stroke_id: str | None = None,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, object] | None:
    edit_payload = dict(edit)
    if stroke_phase is not None:
        edit_payload["stroke_phase"] = str(stroke_phase or "").strip().lower()
    if stroke_id is not None:
        edit_payload["stroke_id"] = str(stroke_id or "").strip()
    payload: dict[str, object] = {"edit": edit_payload}
    if capture_deltas:
        operation = str(edit_payload.get("operation") or "").strip().lower()
        if operation not in {"transform", "brush"} or binary_preview_deltas:
            payload["delta_output_dir"] = _native_preview_delta_output_dir()
        payload["include_edit_report"] = True
        payload["include_preview_deltas"] = bool(include_preview_deltas)
    try:
        if selection is None:
            return native_mesh_editor_session_command(
                "apply",
                session_id,
                payload,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
        with tempfile.TemporaryDirectory(prefix="cdmw_mesh_editor_selection_") as sidecar_root_raw:
            payload["selection"] = _native_mesh_editor_selection_payload(selection, Path(sidecar_root_raw))
            return native_mesh_editor_session_command(
                "apply",
                session_id,
                payload,
                stop_event=stop_event,
                timeout_seconds=timeout_seconds,
            )
    except (OSError, OverflowError, RuntimeError, ValueError):
        return None


def native_mesh_editor_source_normals_payload(
    source_mesh: ParsedMesh,
    submesh_indices: Iterable[int],
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    source_submeshes = tuple(getattr(source_mesh, "submeshes", ()) or ())
    for raw_index in submesh_indices:
        submesh_index = _index(raw_index)
        if submesh_index is None or not 0 <= submesh_index < len(source_submeshes):
            continue
        source = source_submeshes[submesh_index]
        normals = tuple(getattr(source, "normals", ()) or ())
        vertices = tuple(getattr(source, "vertices", ()) or ())
        if not vertices or len(normals) != len(vertices):
            continue
        result[str(submesh_index)] = _write_vec3_binary_payload(
            Path(_native_preview_delta_output_path(f"_copy_normals_source_{submesh_index}.bin")),
            normals,
            fallback=0.0,
        )
    return result


def _apply_native_material_report_attrs(submesh: SubMesh, item: Mapping[str, object]) -> None:
    if "name" in item:
        submesh.name = str(item.get("name") or "")
    if "material" in item:
        submesh.material = str(item.get("material") or "")
    if "texture" in item:
        submesh.texture = str(item.get("texture") or "")
    raw_extra_attrs = item.get("extra_attrs")
    if not isinstance(raw_extra_attrs, Mapping):
        return
    for attr_name in _NATIVE_MATERIAL_REPORT_ATTRS:
        if attr_name in raw_extra_attrs:
            setattr(submesh, attr_name, _snapshot_metadata_value(raw_extra_attrs[attr_name]))
        elif hasattr(submesh, attr_name):
            delattr(submesh, attr_name)


def _apply_native_material_edit_report(
    mesh: ParsedMesh,
    report: Mapping[str, object],
    edit_report: Mapping[str, object],
) -> tuple[set[int], dict[int, Sequence[int] | set[int]]] | None:
    raw_items = edit_report.get("submeshes")
    if not isinstance(raw_items, list):
        return None
    items = [item for item in raw_items if isinstance(item, Mapping)]
    geometry_items = [
        item
        for item in items
        if not bool(item.get("append_submesh"))
        and bool(item.get("topology_changed"))
    ]
    append_items = [item for item in items if bool(item.get("append_submesh"))]
    affected: set[int] = set()
    changed: dict[int, Sequence[int] | set[int]] = {}
    if geometry_items:
        geometry_report = dict(edit_report)
        geometry_report["submeshes"] = geometry_items
        applied = _apply_mesh_edit_report(mesh, geometry_report, skip_topology_normals=True)
        if applied is None:
            return None
        _geometry_affected, geometry_changed = applied
        changed.update(geometry_changed)
    if append_items:
        append_report = dict(edit_report)
        append_report["submeshes"] = append_items
        appended = _append_native_duplicate_report_submeshes(
            mesh,
            append_report,
            recompute_normals=False,
            copy_extra_attrs=True,
            reset_source_descriptors=True,
        )
        if appended is None:
            return None
        affected.update(appended)
    for item in items:
        submesh_index = _index(item.get("index"))
        if submesh_index is None or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        has_material_metadata = "material" in item or "texture" in item or isinstance(item.get("extra_attrs"), Mapping)
        if not has_material_metadata:
            continue
        _apply_native_material_report_attrs(mesh.submeshes[submesh_index], item)
        affected.add(submesh_index)
    raw_affected = report.get("affected_submesh_indices")
    if not affected and isinstance(raw_affected, list):
        affected = {
            index
            for index in (_index(value) for value in raw_affected)
            if index is not None and 0 <= index < len(mesh.submeshes)
        } or affected
    _reconcile_native_editor_submesh_count(mesh, report)
    _refresh_mesh_totals(mesh)
    return affected, changed


def native_mesh_editor_session_preview_triangle_groups(
    report: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    if not isinstance(report, Mapping):
        return ()
    edit_report = report.get("edit_report")
    if not isinstance(edit_report, Mapping):
        return ()
    raw_items = edit_report.get("submeshes")
    if not isinstance(raw_items, list):
        return ()
    groups: list[Mapping[str, object]] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        submesh_index = _index(item.get("index"))
        if submesh_index is None:
            continue
        group = _native_preview_triangle_group(item.get("preview_triangle_group"), submesh_index)
        if group is not None:
            groups.append(_native_preview_triangle_group_with_report_material(group, item, submesh_index))
    return tuple(groups)


def native_mesh_editor_session_preview_vertex_update_groups(
    report: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    if not isinstance(report, Mapping):
        return ()
    edit_report = report.get("edit_report")
    if not isinstance(edit_report, Mapping):
        return ()
    raw_items = edit_report.get("submeshes")
    if not isinstance(raw_items, list):
        return ()
    groups: list[Mapping[str, object]] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        submesh_index = _index(item.get("index"))
        if submesh_index is None:
            continue
        group = _native_preview_vertex_update_group(item.get("preview_vertex_update_group"), submesh_index)
        if group is not None:
            groups.append(group)
    return tuple(groups)


def _native_preview_triangle_group_with_report_material(
    group: Mapping[str, object],
    item: Mapping[str, object],
    submesh_index: int,
) -> dict[str, object]:
    result = dict(group)
    if "name" in item:
        result.setdefault("part_name", str(item.get("name") or f"part_{submesh_index}"))
    if "material" in item or "name" in item:
        result.setdefault("material_name", str(item.get("material") or item.get("name") or f"part_{submesh_index}"))
    if "texture" in item:
        result.setdefault("texture_name", str(item.get("texture") or ""))
    source_index = _index(item.get("source_index"))
    if source_index is not None and bool(item.get("append_submesh")):
        result.setdefault("material_source_submesh_index", source_index)
    raw_extra_attrs = item.get("extra_attrs")
    if isinstance(raw_extra_attrs, Mapping):
        material_source = _index(raw_extra_attrs.get("cdmw_mesh_edit_material_source_submesh_index"))
        if material_source is not None:
            result["material_source_submesh_index"] = material_source
        for attr_name in ("preview_alpha_mode", "preview_texture_flip_vertical", "preview_double_sided"):
            if attr_name in raw_extra_attrs:
                result.setdefault(attr_name, raw_extra_attrs[attr_name])
        overrides = raw_extra_attrs.get("preview_native_material_overrides")
        if isinstance(overrides, Mapping):
            for key in _NATIVE_PREVIEW_MATERIAL_OVERRIDE_KEYS:
                if key in overrides:
                    result.setdefault(key, overrides[key])
    return result


def _reconcile_native_editor_submesh_count(mesh: ParsedMesh, report: Mapping[str, object]) -> None:
    count = _index(report.get("submesh_count"))
    if count is None or count < 0:
        return
    if count < len(mesh.submeshes):
        del mesh.submeshes[count:]


def summarize_native_mesh_editor_session(
    session_id: str,
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 2.0,
) -> dict[str, object] | None:
    return native_mesh_editor_session_command(
        "summary",
        session_id,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )


def undo_native_mesh_editor_session(
    session_id: str,
    *,
    capture_deltas: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, object] | None:
    payload: dict[str, object] = {}
    if capture_deltas:
        payload["delta_output_dir"] = _native_preview_delta_output_dir()
        payload["include_edit_report"] = True
    return native_mesh_editor_session_command(
        "undo",
        session_id,
        payload,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )


def redo_native_mesh_editor_session(
    session_id: str,
    *,
    capture_deltas: bool = True,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, object] | None:
    payload: dict[str, object] = {}
    if capture_deltas:
        payload["delta_output_dir"] = _native_preview_delta_output_dir()
        payload["include_edit_report"] = True
    return native_mesh_editor_session_command(
        "redo",
        session_id,
        payload,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )


def export_native_mesh_editor_session_snapshot(
    session_id: str,
    submeshes: Sequence[Mapping[str, object]] | None = None,
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, object] | None:
    payload: dict[str, object] = {}
    if submeshes is not None:
        payload["submeshes"] = [dict(item) for item in submeshes]
    return native_mesh_editor_session_command(
        "export_snapshot",
        session_id,
        payload,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )


def export_native_mesh_editor_session_to_mesh(
    mesh: ParsedMesh,
    session_id: str,
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 10.0,
) -> bool:
    if not isinstance(mesh, ParsedMesh):
        return False
    summary = export_native_mesh_editor_session_snapshot(
        session_id,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )
    raw_summary_items = summary.get("submeshes") if isinstance(summary, Mapping) else None
    summary_by_index: dict[int, Mapping[str, object]] = {}
    if isinstance(raw_summary_items, list):
        for raw_item in raw_summary_items:
            if not isinstance(raw_item, Mapping):
                continue
            submesh_index = _index(raw_item.get("index"))
            if submesh_index is not None and submesh_index >= 0:
                summary_by_index[submesh_index] = raw_item
    requested = tuple(sorted(summary_by_index)) or tuple(range(len(getattr(mesh, "submeshes", ()) or ())))
    if not requested:
        return True
    job_submeshes: list[dict[str, object]] = []
    metadata_by_index: dict[int, dict[str, object]] = {}
    for submesh_index in requested:
        if 0 <= submesh_index < len(mesh.submeshes):
            metadata = _submesh_snapshot_metadata(mesh.submeshes[submesh_index])
        else:
            metadata = _submesh_snapshot_metadata(SubMesh())
        summary_item = summary_by_index.get(submesh_index, {})
        for key in ("name", "material", "texture"):
            if key in summary_item:
                metadata[key] = str(summary_item.get(key) or "")
        if isinstance(summary_item.get("extra_attrs"), Mapping):
            metadata["extra_attrs"] = dict(summary_item["extra_attrs"])
        else:
            metadata.pop("extra_attrs", None)
        metadata_by_index[submesh_index] = metadata
        job_submeshes.append(
            {
                "index": submesh_index,
                "vertices_output_path": _native_preview_delta_output_path("_editor_snapshot_vertices.bin"),
                "faces_output_path": _native_preview_delta_output_path("_editor_snapshot_faces.bin"),
                "source_face_indices_output_path": _native_preview_delta_output_path("_editor_snapshot_source_faces.bin"),
                "normals_output_path": _native_preview_delta_output_path("_editor_snapshot_normals.bin"),
                "uvs_output_path": _native_preview_delta_output_path("_editor_snapshot_uvs.bin"),
                "tangents_output_path": _native_preview_delta_output_path("_editor_snapshot_tangents.bin"),
                "tangent_signs_output_path": _native_preview_delta_output_path("_editor_snapshot_tangent_signs.bin"),
                "bone_counts_output_path": _native_preview_delta_output_path("_editor_snapshot_bone_counts.bin"),
                "bone_indices_output_path": _native_preview_delta_output_path("_editor_snapshot_bone_indices.bin"),
                "bone_weights_output_path": _native_preview_delta_output_path("_editor_snapshot_bone_weights.bin"),
                "source_vertex_map_output_path": _native_preview_delta_output_path("_editor_snapshot_source_vertex_map.bin"),
                "source_vertex_offsets_output_path": _native_preview_delta_output_path("_editor_snapshot_source_vertex_offsets.bin"),
            }
        )
    report = export_native_mesh_editor_session_snapshot(
        session_id,
        job_submeshes,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )
    raw_items = report.get("submeshes") if isinstance(report, Mapping) else None
    if not isinstance(raw_items, list):
        return False
    snapshot_items: dict[int, dict[str, object]] = {}
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            return False
        submesh_index = _index(raw_item.get("index"))
        vertex_count = _index(raw_item.get("vertex_count"))
        face_count = _index(raw_item.get("face_count"))
        if submesh_index is None or vertex_count is None or face_count is None:
            return False
        if submesh_index not in metadata_by_index:
            return False
        metadata = dict(metadata_by_index[submesh_index])
        for key in ("name", "material", "texture"):
            if key in raw_item:
                metadata[key] = str(raw_item.get(key) or "")
        if isinstance(raw_item.get("extra_attrs"), Mapping):
            metadata["extra_attrs"] = dict(raw_item["extra_attrs"])
        else:
            metadata.pop("extra_attrs", None)
        snapshot_item = _native_submesh_snapshot_item(
            raw_item,
            metadata=metadata,
            expected_vertices=vertex_count,
            expected_faces=face_count,
        )
        if snapshot_item is None:
            return False
        snapshot_items[submesh_index] = snapshot_item
    if set(snapshot_items) != set(requested):
        return False
    return restore_native_mesh_submesh_snapshot(
        mesh,
        {
            "kind": "native_submesh_snapshot",
            "mesh": _mesh_snapshot_metadata(mesh),
            "submeshes": [snapshot_items[index] for index in requested],
        },
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )


def close_native_mesh_editor_session(
    session_id: str,
    *,
    stop_event: threading.Event | None = None,
    timeout_seconds: float = 2.0,
) -> dict[str, object] | None:
    return native_mesh_editor_session_command(
        "close",
        session_id,
        stop_event=stop_event,
        timeout_seconds=timeout_seconds,
    )
