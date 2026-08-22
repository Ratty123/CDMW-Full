from __future__ import annotations

import copy
from collections.abc import Mapping

from cdmw.modding.mesh_deformer import copy_extra_submesh_attrs
from cdmw.modding.mesh_edit_ops import refresh_mesh_totals
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.services.mesh_service_native_session import (
    _allow_python_service_clone_fallback,
    _service_call,
)
from cdmw.services.mesh_service_state import _MeshEditSession, _MeshHistorySnapshot


def _copy_mesh_validation_metadata(source: ParsedMesh, target: ParsedMesh) -> None:
    for name in (
        "_cdmw_original_data",
        "_cdmw_mesh_asset_parse_confidence",
        "_cdmw_mesh_asset_source_hash",
        "_cdmw_mesh_asset_inferred_bone_count",
        "_cdmw_no_op_roundtrip_report",
        "_cdmw_mesh_asset_lods",
        "_cdmw_mesh_asset_material_slots",
        "_cdmw_mesh_asset_unknown_sections",
        "_cdmw_sidecar_source_asset_hash",
        "_cdmw_sidecar_source_asset_size",
        "material_slots",
        "unknown_sections",
    ):
        if hasattr(source, name):
            setattr(target, name, copy.deepcopy(getattr(source, name)))
    for source_submesh, target_submesh in zip(tuple(source.submeshes or ()), tuple(target.submeshes or ())):
        copy_extra_submesh_attrs(source_submesh, target_submesh)


def _clone_mesh_pair_for_session_open(mesh: ParsedMesh) -> tuple[ParsedMesh, ParsedMesh]:
    if not _service_session_native_clone_supported(mesh):
        return _clone_mesh_pair_for_service_python_fallback(
            mesh,
            "session.open_clone_unsupported_topology",
            "Python edit-session open clone fallback used for unsupported topology",
            guard_native_supported=False,
        )
    native_snapshot: Mapping[str, object] | None = None
    try:
        native_snapshot = _service_call("snapshot_native_mesh_submeshes", mesh)  # type: ignore[assignment]
        if native_snapshot is not None:
            working_mesh = ParsedMesh()
            base_mesh = ParsedMesh()
            if (
                _service_call("restore_native_mesh_submesh_snapshot", working_mesh, native_snapshot)
                and _service_call("restore_native_mesh_submesh_snapshot", base_mesh, native_snapshot)
            ):
                refresh_mesh_totals(working_mesh)
                refresh_mesh_totals(base_mesh)
                return working_mesh, base_mesh
    except Exception:
        pass
    finally:
        if native_snapshot is not None:
            _service_call("dispose_native_mesh_submesh_snapshot", native_snapshot)
    return _clone_mesh_pair_for_service_python_fallback(
        mesh,
        "session.open_clone",
        "Python edit-session open clone fallback blocked while native mesh core is available",
    )


def _clone_mesh_for_service_native_snapshot(mesh: ParsedMesh, operation: str, reason: str) -> ParsedMesh:
    if not _service_session_native_clone_supported(mesh):
        return _clone_mesh_for_service_python_fallback(
            mesh,
            f"{operation}.unsupported_topology",
            reason,
            guard_native_supported=False,
        )
    native_snapshot: Mapping[str, object] | None = None
    try:
        native_snapshot = _service_call("snapshot_native_mesh_submeshes", mesh)  # type: ignore[assignment]
        if native_snapshot is not None:
            restored_mesh = ParsedMesh()
            if _service_call("restore_native_mesh_submesh_snapshot", restored_mesh, native_snapshot):
                refresh_mesh_totals(restored_mesh)
                _copy_mesh_validation_metadata(mesh, restored_mesh)
                return restored_mesh
    except Exception:
        pass
    finally:
        if native_snapshot is not None:
            _service_call("dispose_native_mesh_submesh_snapshot", native_snapshot)
    return _clone_mesh_for_service_python_fallback(mesh, operation, reason)


def _clone_history_snapshot_for_python_fallback(session: _MeshEditSession) -> _MeshHistorySnapshot:
    return _MeshHistorySnapshot(
        mesh=_service_call("clone_mesh_for_editing", session.working_mesh),  # type: ignore[arg-type]
        mode=session.mode,
        selection=session.selection,
        edit_operations=tuple(session.edit_operations),
        material_generation=session.material_generation,
        committed_texture_resources=tuple(
            session.committed_texture_resources[key]
            for key in sorted(session.committed_texture_resources)
        ),
        object_transform=session.object_transform,
    )


def _clone_mesh_pair_for_service_python_fallback(
    mesh: ParsedMesh,
    operation: str,
    reason: str,
    *,
    guard_native_supported: bool = True,
) -> tuple[ParsedMesh, ParsedMesh]:
    if guard_native_supported and not _allow_python_service_clone_fallback(mesh, operation, reason):
        raise RuntimeError("native edit-session clone failed and Python fallback was blocked")
    return (
        _service_call("clone_mesh_for_editing", mesh),  # type: ignore[return-value]
        _service_call("clone_mesh_for_editing", mesh),  # type: ignore[return-value]
    )


def _clone_mesh_for_service_python_fallback(
    mesh: ParsedMesh,
    operation: str,
    reason: str,
    *,
    guard_native_supported: bool = True,
) -> ParsedMesh:
    if guard_native_supported and not _allow_python_service_clone_fallback(mesh, operation, reason):
        raise RuntimeError("native mesh clone failed and Python fallback was blocked")
    cloned = _service_call("clone_mesh_for_editing", mesh)
    _copy_mesh_validation_metadata(mesh, cloned)
    return cloned  # type: ignore[return-value]


def _service_session_native_clone_supported(mesh: ParsedMesh) -> bool:
    for submesh in mesh.submeshes or ():
        vertex_count = len(submesh.vertices or ())
        for raw_face in submesh.faces or ():
            if len(raw_face) != 3:
                return False
            for raw_index in raw_face:
                try:
                    vertex_index = int(raw_index)
                except (TypeError, ValueError, OverflowError):
                    return False
                if vertex_index < 0 or vertex_index >= vertex_count:
                    return False
    return True


__all__ = [
    "_clone_history_snapshot_for_python_fallback",
    "_clone_mesh_for_service_native_snapshot",
    "_clone_mesh_for_service_python_fallback",
    "_clone_mesh_pair_for_service_python_fallback",
    "_clone_mesh_pair_for_session_open",
    "_copy_mesh_validation_metadata",
    "_service_session_native_clone_supported",
]
