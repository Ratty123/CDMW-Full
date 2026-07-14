"""Detached prepare and narrow atomic commit for imported mesh replacements."""

from __future__ import annotations

import sys

from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.services.mesh_service_state import (
    MeshPreparedWorkingMeshReplacement,
    _MeshEditSession,
)


def _service_call(name: str, *args: object, **kwargs: object) -> object:
    return getattr(sys.modules["cdmw.services.mesh_service"], name)(*args, **kwargs)


def _publish_prepared_replacement(
    session: _MeshEditSession,
    prepared: MeshPreparedWorkingMeshReplacement,
) -> None:
    """Publish only already-validated values; kept narrow for rollback testing."""

    session.working_mesh = prepared.working_mesh
    session.selection = prepared.selection
    session.sidecar_warnings = prepared.sidecar_warnings
    session.edit_operations = prepared.edit_operations
    session.requires_edit_operations = prepared.requires_edit_operations
    session.revision += 1


def _restore_previous_replacement_state(
    session: _MeshEditSession,
    prepared: MeshPreparedWorkingMeshReplacement,
) -> None:
    session.working_mesh = prepared.previous_working_mesh
    session.selection = prepared.previous_selection
    session.sidecar_warnings = prepared.previous_sidecar_warnings
    session.edit_operations = prepared.previous_edit_operations
    session.requires_edit_operations = prepared.previous_requires_edit_operations
    session.revision = prepared.expected_revision


class MeshWorkingReplacementServiceMixin:
    def replace_working_mesh(self, session_id: str, mesh: ParsedMesh):
        prepared = self.prepare_working_mesh_replacement(session_id, mesh)
        return self.commit_prepared_working_mesh_replacement(prepared)

    def prepare_working_mesh_replacement(
        self,
        session_id: str,
        mesh: ParsedMesh,
    ) -> MeshPreparedWorkingMeshReplacement:
        """Build and validate an immutable candidate without publishing live state."""

        session = self._session(session_id)
        with session.export_lock:
            if session.closed:
                raise KeyError(f"Unknown mesh edit session: {session_id}")
            if not isinstance(mesh, ParsedMesh):
                raise TypeError("mesh must be a ParsedMesh")

            previous_working_mesh = _service_call(
                "_clone_mesh_for_service_native_snapshot",
                session.working_mesh,
                "session.prepared_replacement_previous",
                "Python replacement preparation clone fallback blocked while native mesh core is available",
            )
            if session.native_editor_mesh_dirty:
                if not session.native_editor_session_ready or not _service_call(
                    "export_native_mesh_editor_session_to_mesh",
                    previous_working_mesh,
                    session.session_id,
                    timeout_seconds=20.0,
                ):
                    raise RuntimeError(
                        "native mesh editor replacement preparation failed; authoritative resident state was not changed"
                    )
                _service_call("refresh_mesh_totals", previous_working_mesh)

            if bool(getattr(mesh, "_cdmw_imported_from_obj", False)) and bool(
                getattr(mesh, "_cdmw_obj_sidecar_present", False)
            ):
                _service_call("validate_obj_sidecar_source_identity", mesh, session.original_data)
            working_mesh = _service_call(
                "apply_operation_channels_to_original", session.base_mesh, mesh
            )
            if session.original_data:
                setattr(working_mesh, "_cdmw_original_data", session.original_data)
            if not str(working_mesh.format or "").strip():
                working_mesh.format = session.base_mesh.format
            if not str(working_mesh.path or "").strip():
                working_mesh.path = session.base_mesh.path
            _service_call("refresh_mesh_totals", working_mesh)
            preserved_selection, selection_diagnostics = _service_call(
                "_selection_after_working_mesh_replace",
                previous_working_mesh,
                working_mesh,
                session.selection,
            )
            if selection_diagnostics:
                setattr(working_mesh, "_cdmw_selection_diagnostics", selection_diagnostics)
            sidecar_warnings = tuple(getattr(working_mesh, "_cdmw_sidecar_warnings", ()) or ())
            edit_operations = tuple(getattr(working_mesh, "_cdmw_edit_operations", ()) or ())
            requires_edit_operations = bool(
                getattr(working_mesh, "_cdmw_requires_edit_operations", False)
            ) or (
                bool(getattr(working_mesh, "_cdmw_imported_from_obj", False))
                and bool(getattr(working_mesh, "_cdmw_obj_sidecar_present", False))
            )
            validation_report = _service_call(
                "validate_mesh_export",
                working_mesh,
                original_mesh=session.base_mesh,
                skeleton_bone_count=_service_call(
                    "_session_validation_skeleton_bone_count", session
                ),
                parse_confidence=session.mesh_asset_parse_confidence,
                source_asset_hash=session.mesh_asset_source_hash,
                no_op_roundtrip_status=_service_call("_session_roundtrip_status", session),
                no_op_byte_identical=_service_call("_session_roundtrip_byte_identical", session),
                no_op_unexpected_differences=_service_call(
                    "_session_roundtrip_unexpected_differences", session
                ),
                sidecar_warnings=sidecar_warnings,
                edit_operations=edit_operations,
                requires_edit_operations=requires_edit_operations,
            )
            return MeshPreparedWorkingMeshReplacement(
                session_id=session.session_id,
                expected_revision=session.revision,
                working_mesh=working_mesh,
                selection=preserved_selection,
                previous_working_mesh=previous_working_mesh,
                previous_selection=session.selection,
                validation_report=validation_report,
                previous_sidecar_warnings=tuple(session.sidecar_warnings),
                previous_edit_operations=tuple(session.edit_operations),
                previous_requires_edit_operations=session.requires_edit_operations,
                sidecar_warnings=sidecar_warnings,
                edit_operations=edit_operations,
                requires_edit_operations=requires_edit_operations,
            )

    def commit_prepared_working_mesh_replacement(
        self,
        prepared: MeshPreparedWorkingMeshReplacement,
    ):
        """Atomically publish a validated replacement if its session is unchanged."""

        if not isinstance(prepared, MeshPreparedWorkingMeshReplacement):
            raise TypeError("prepared must be a MeshPreparedWorkingMeshReplacement")
        session = self._session(prepared.session_id)
        with session.export_lock:
            if session.closed:
                raise KeyError(f"Unknown mesh edit session: {prepared.session_id}")
            if session.revision != prepared.expected_revision:
                raise RuntimeError(
                    "Prepared mesh replacement is stale: "
                    f"expected revision {prepared.expected_revision}, current revision {session.revision}."
                )

            history_snapshot = _service_call("_snapshot", session, prefer_native=True)
            history_snapshot.history_action = "replace_working_mesh"
            history_snapshot.history_label = "Replace Working Mesh"
            history_snapshot.retained_bytes = _service_call(
                "_history_snapshot_retained_bytes", history_snapshot
            )
            old_undo = list(session.undo_stack)
            old_redo = list(session.redo_stack)
            _service_call("_close_native_editor_session", session)
            session.undo_stack.append(history_snapshot)
            try:
                _publish_prepared_replacement(session, prepared)
            except Exception:
                _restore_previous_replacement_state(session, prepared)
                session.undo_stack[:] = old_undo
                session.redo_stack[:] = old_redo
                raise
            _service_call("_clear_history_stack", session.redo_stack)
            self._trim_session_history(session)
            return self._session_view_locked(session)


__all__ = ["MeshWorkingReplacementServiceMixin"]
