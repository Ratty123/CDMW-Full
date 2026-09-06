"""Detached prepare and narrow atomic commit for imported mesh replacements."""

from __future__ import annotations

import copy
import sys
from dataclasses import dataclass
from collections.abc import Sequence

from cdmw.domain.mesh import MeshObjectTransformState
from cdmw.domain.mesh.authoring_capability import MeshOutputPolicy, output_policy_state
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.services.mesh_service_state import (
    MeshPreparedWorkingMeshReplacement,
    _MeshEditSession,
    _MeshHistorySnapshot,
    _MeshMorphSessionState,
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
    session.object_transform = MeshObjectTransformState(pivot=session.object_transform.pivot)
    session.revision += 1


def _restore_previous_replacement_state(
    session: _MeshEditSession,
    prepared: MeshPreparedWorkingMeshReplacement,
) -> None:
    session.working_mesh = prepared.previous_working_mesh
    session.selection = prepared.previous_selection
    session.object_transform = prepared.previous_object_transform
    session.sidecar_warnings = prepared.previous_sidecar_warnings
    session.edit_operations = prepared.previous_edit_operations
    session.requires_edit_operations = prepared.previous_requires_edit_operations
    session.revision = prepared.expected_revision


@dataclass(frozen=True, slots=True)
class _ReplacementOptions:
    history_action: str
    history_label: str
    geometry_layers: Sequence[object] | None
    active_geometry_layer_id: str | None
    geometry_layer_copy_counter: int | None
    object_transform: MeshObjectTransformState | None
    output_policy: str | None
    output_destination: str | None
    output_destination_ready: bool | None
    morph_session_state: _MeshMorphSessionState | None
    morph_profile_root: str | None
    morph_profile_root_existed: bool | None
    morph_profile_files: Sequence[tuple[str, bytes]] | None
    morph_profile_after_root_existed: bool | None
    morph_profile_after_files: Sequence[tuple[str, bytes]] | None
    morph_profile_expected_fingerprint: str | None
    require_reversible_history: bool


@dataclass(frozen=True, slots=True)
class _ReplacementCheckpoint:
    old_undo: list[_MeshHistorySnapshot]
    old_redo: list[_MeshHistorySnapshot]
    old_geometry_layers: tuple
    old_active_geometry_layer_id: str
    old_geometry_layer_copy_counter: int
    old_geometry_layer_revision: int
    old_output_policy: str
    old_output_destination: str
    old_output_destination_ready: bool
    old_morph_session_revision: int


class MeshWorkingReplacementServiceMixin:
    def replace_working_mesh(self, session_id: str, mesh: ParsedMesh):
        prepared = self.prepare_working_mesh_replacement(session_id, mesh)
        return self.commit_prepared_working_mesh_replacement(prepared)

    def prepare_working_mesh_replacement(
        self,
        session_id: str,
        mesh: ParsedMesh,
        *,
        validation_output_policy: str | None = None,
        validation_output_destination: str | None = None,
        validation_output_destination_ready: bool | None = None,
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
                "apply_operation_channels_to_original",
                session.base_mesh,
                mesh,
                active_lod_index=session.lod_index,
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
            requested_output_policy = (
                session.output_policy
                if validation_output_policy is None
                else str(validation_output_policy)
            )
            requested_output_destination = (
                session.output_destination
                if validation_output_destination is None
                else str(validation_output_destination)
            )
            requested_output_destination_ready = (
                session.output_destination_ready
                if validation_output_destination_ready is None
                else bool(validation_output_destination_ready)
            )
            validation_policy = output_policy_state(
                session.mesh_format,
                lod_index=session.lod_index,
                requested_policy=requested_output_policy,
                output_destination=requested_output_destination,
                destination_ready=requested_output_destination_ready,
            )
            if validation_policy.policy.value != requested_output_policy:
                raise RuntimeError(
                    validation_policy.reason
                    or "The requested Mesh Editor output policy is unavailable."
                )
            allowed_operation_lods = (
                (session.lod_index,)
                if validation_policy.policy is MeshOutputPolicy.FREE_EDIT
                and validation_policy.authoring_enabled
                else None
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
                allowed_operation_lod_indices=allowed_operation_lods,
                require_operation_source_mapping=(
                    validation_policy.policy is not MeshOutputPolicy.FREE_EDIT
                ),
                exact_output=(validation_policy.policy is not MeshOutputPolicy.FREE_EDIT),
            )
            return MeshPreparedWorkingMeshReplacement(
                session_id=session.session_id,
                expected_revision=session.revision,
                working_mesh=working_mesh,
                selection=preserved_selection,
                previous_working_mesh=previous_working_mesh,
                previous_selection=session.selection,
                previous_object_transform=session.object_transform,
                validation_report=validation_report,
                previous_sidecar_warnings=tuple(session.sidecar_warnings),
                previous_edit_operations=tuple(session.edit_operations),
                previous_requires_edit_operations=session.requires_edit_operations,
                sidecar_warnings=sidecar_warnings,
                edit_operations=edit_operations,
                requires_edit_operations=requires_edit_operations,
            )

    def _publish_replacement_with_rollback(self, session, prepared, history_snapshot, next_undo, next_redo, options, checkpoint):
        try:
            _publish_prepared_replacement(session, prepared)
            if options.geometry_layers is not None:
                session.geometry_layers = tuple(copy.deepcopy(tuple(options.geometry_layers)))
                if options.active_geometry_layer_id is not None:
                    session.active_geometry_layer_id = str(options.active_geometry_layer_id or "base")
                if options.geometry_layer_copy_counter is not None:
                    session.geometry_layer_copy_counter = max(
                        0,
                        int(options.geometry_layer_copy_counter),
                    )
                session.geometry_layer_revision = checkpoint.old_geometry_layer_revision + 1
            if options.object_transform is not None:
                if not isinstance(options.object_transform, MeshObjectTransformState):
                    raise TypeError("object_transform must be MeshObjectTransformState")
                session.object_transform = copy.deepcopy(options.object_transform)
            if options.output_policy is not None:
                session.output_policy = str(options.output_policy)
            if options.output_destination is not None:
                session.output_destination = str(options.output_destination)
            if options.output_destination_ready is not None:
                session.output_destination_ready = bool(options.output_destination_ready)
            if options.morph_session_state is not None:
                self._install_morph_session_state_locked(
                    session,
                    options.morph_session_state,
                )
            if options.morph_profile_root is not None and options.morph_session_state is None:
                self._morph_sessions.pop(prepared.session_id, None)
            session.undo_stack[:] = next_undo
            session.redo_stack[:] = next_redo
            committed_view = self._session_view_locked(session)
        except Exception as commit_error:
            close_error = None
            try:
                _service_call("_close_native_editor_session", session)
            except Exception as exc:
                close_error = exc
            rollback_errors: list[Exception] = []
            try:
                _restore_previous_replacement_state(session, prepared)
                session.geometry_layers = checkpoint.old_geometry_layers
                session.active_geometry_layer_id = checkpoint.old_active_geometry_layer_id
                session.geometry_layer_copy_counter = checkpoint.old_geometry_layer_copy_counter
                session.geometry_layer_revision = checkpoint.old_geometry_layer_revision
                session.output_policy = checkpoint.old_output_policy
                session.output_destination = checkpoint.old_output_destination
                session.output_destination_ready = checkpoint.old_output_destination_ready
                # The resident history was destroyed at the replacement
                # boundary. Keep only history entries that remain valid.
                session.undo_stack[:] = [
                    snapshot for snapshot in checkpoint.old_undo if not snapshot.native_editor_history
                ]
                session.redo_stack[:] = [
                    snapshot for snapshot in checkpoint.old_redo if not snapshot.native_editor_history
                ]
            except Exception as exc:
                rollback_errors.append(exc)
            morph_restore_error = None
            if history_snapshot.morph_session_state is not None:
                try:
                    self._install_morph_session_state_locked(
                        session,
                        history_snapshot.morph_session_state,
                        reconcile_profiles=False,
                        advance_revision=False,
                    )
                except Exception as exc:  # pragma: no cover - catastrophic native rollback
                    morph_restore_error = exc
            try:
                _service_call("_dispose_history_snapshot", history_snapshot)
            except Exception as exc:
                session.mesh_layer_autosave_error = f"{type(exc).__name__}: {exc}"
            for invalid_marker in (
                snapshot
                for snapshot in (*checkpoint.old_undo, *checkpoint.old_redo)
                if snapshot.native_editor_history
            ):
                try:
                    _service_call("_dispose_history_snapshot", invalid_marker)
                except Exception as exc:
                    session.mesh_layer_autosave_error = f"{type(exc).__name__}: {exc}"
            if close_error is not None:
                session.mesh_layer_autosave_error = (
                    f"{type(close_error).__name__}: {close_error}"
                )
            if morph_restore_error is not None:
                rollback_errors.append(morph_restore_error)
            if close_error is not None or rollback_errors:
                # A partial/failed rollback must never advertise the old
                # CAS tokens for state that may no longer match them.
                session.revision = max(
                    int(session.revision),
                    int(prepared.expected_revision),
                ) + 1
                session.geometry_layer_revision = max(
                    int(session.geometry_layer_revision),
                    int(checkpoint.old_geometry_layer_revision),
                ) + 1
                session.morph_session_revision = max(
                    int(session.morph_session_revision),
                    int(checkpoint.old_morph_session_revision),
                ) + 1
            else:
                session.morph_session_revision = checkpoint.old_morph_session_revision
            if rollback_errors:
                raise RuntimeError(
                    "Prepared mesh replacement failed and its authoritative rollback also failed."
                ) from rollback_errors[0]
            raise commit_error
        return committed_view


    def _capture_replacement_history(self, session, prepared, options):
        history_snapshot = None
        try:
            history_snapshot = _service_call("_snapshot", session, prefer_native=True)
            history_snapshot.history_action = str(options.history_action or "replace_working_mesh")
            history_snapshot.history_label = str(options.history_label or "Replace Working Mesh")
            if session.native_editor_mesh_dirty:
                previous_native_snapshot = _service_call(
                    "snapshot_native_mesh_submeshes",
                    prepared.previous_working_mesh,
                )
                if previous_native_snapshot is None:
                    raise RuntimeError(
                        "Prepared mesh replacement could not capture the authoritative "
                        "resident geometry for reversible history."
                    )
                history_snapshot.mesh = None
                history_snapshot.native_submesh_snapshot = previous_native_snapshot
            if options.geometry_layers is not None:
                history_snapshot.geometry_layers = tuple(copy.deepcopy(session.geometry_layers))
                history_snapshot.active_geometry_layer_id = session.active_geometry_layer_id
                history_snapshot.geometry_layer_copy_counter = session.geometry_layer_copy_counter
                history_snapshot.restore_geometry_layer_state = True
            if options.output_policy is not None:
                history_snapshot.output_policy = session.output_policy
            if options.output_destination is not None:
                history_snapshot.output_destination = session.output_destination
            if options.output_destination_ready is not None:
                history_snapshot.output_destination_ready = session.output_destination_ready
            if options.morph_session_state is not None:
                history_snapshot.morph_session_state = (
                    self._capture_morph_session_state_locked(session)
                )
            if options.morph_profile_root is not None:
                if (
                    options.morph_profile_root_existed is None
                    or options.morph_profile_files is None
                    or not str(options.morph_profile_expected_fingerprint or "").strip()
                ):
                    raise ValueError(
                        "Morph profile history requires the prior tree and expected fingerprint"
                    )
                if options.require_reversible_history and (
                    options.morph_profile_after_root_existed is None
                    or options.morph_profile_after_files is None
                ):
                    raise ValueError(
                        "Reversible Morph profile history requires the committed tree state"
                    )
                history_snapshot.morph_profile_root = str(options.morph_profile_root)
                history_snapshot.morph_profile_root_existed = bool(options.morph_profile_root_existed)
                history_snapshot.morph_profile_files = tuple(
                    (str(relative), bytes(data)) for relative, data in options.morph_profile_files
                )
                history_snapshot.morph_profile_expected_fingerprint = str(
                    options.morph_profile_expected_fingerprint
                ).upper()
            history_snapshot.retained_bytes = _service_call(
                "_history_snapshot_retained_bytes", history_snapshot
            )
            if options.require_reversible_history:
                history_limit = max(0, int(self.max_history_bytes or 0))
                if history_snapshot.retained_bytes > history_limit:
                    raise RuntimeError(
                        "Edit Session cannot be committed because its reversible history "
                        "snapshot exceeds the configured history memory limit."
                    )
                after_snapshot = _MeshHistorySnapshot(
                    mesh=prepared.working_mesh,
                    mode=session.mode,
                    selection=prepared.selection,
                    edit_operations=tuple(prepared.edit_operations),
                    geometry_layers=(
                        tuple(copy.deepcopy(tuple(options.geometry_layers)))
                        if options.geometry_layers is not None
                        else None
                    ),
                    active_geometry_layer_id=(
                        str(options.active_geometry_layer_id or "base")
                        if options.geometry_layers is not None
                        else None
                    ),
                    geometry_layer_copy_counter=(
                        max(0, int(options.geometry_layer_copy_counter or 0))
                        if options.geometry_layers is not None
                        else None
                    ),
                    restore_geometry_layer_state=options.geometry_layers is not None,
                    output_policy=(str(options.output_policy) if options.output_policy is not None else None),
                    output_destination=(
                        str(options.output_destination) if options.output_destination is not None else None
                    ),
                    output_destination_ready=(
                        bool(options.output_destination_ready)
                        if options.output_destination_ready is not None
                        else None
                    ),
                    morph_profile_root=(
                        str(options.morph_profile_root) if options.morph_profile_root is not None else None
                    ),
                    morph_profile_root_existed=(
                        bool(options.morph_profile_after_root_existed)
                        if options.morph_profile_root is not None
                        else None
                    ),
                    morph_profile_files=(
                        tuple(
                            (str(relative), bytes(data))
                            for relative, data in tuple(options.morph_profile_after_files or ())
                        )
                        if options.morph_profile_root is not None
                        else None
                    ),
                    morph_profile_expected_fingerprint=(
                        str(options.morph_profile_expected_fingerprint or "").upper()
                        if options.morph_profile_root is not None
                        else None
                    ),
                    morph_session_state=options.morph_session_state,
                    object_transform=(
                        copy.deepcopy(options.object_transform)
                        if options.object_transform is not None
                        else copy.deepcopy(session.object_transform)
                    ),
                )
                after_retained_bytes = int(
                    _service_call("_history_snapshot_retained_bytes", after_snapshot)
                )
                if after_retained_bytes > history_limit:
                    raise RuntimeError(
                        "Edit Session cannot be committed because its result cannot fit "
                        "the configured reversible history memory limit."
                    )
        except Exception:
            if history_snapshot is not None:
                _service_call("_dispose_history_snapshot", history_snapshot)
            raise
        return history_snapshot


    def commit_prepared_working_mesh_replacement(
        self,
        prepared: MeshPreparedWorkingMeshReplacement,
        *,
        history_action: str = "replace_working_mesh",
        history_label: str = "Replace Working Mesh",
        geometry_layers: Sequence[object] | None = None,
        active_geometry_layer_id: str | None = None,
        geometry_layer_copy_counter: int | None = None,
        object_transform: MeshObjectTransformState | None = None,
        output_policy: str | None = None,
        output_destination: str | None = None,
        output_destination_ready: bool | None = None,
        expected_geometry_layer_revision: int | None = None,
        expected_morph_session_revision: int | None = None,
        morph_session_state: _MeshMorphSessionState | None = None,
        morph_profile_root: str | None = None,
        morph_profile_root_existed: bool | None = None,
        morph_profile_files: Sequence[tuple[str, bytes]] | None = None,
        morph_profile_after_root_existed: bool | None = None,
        morph_profile_after_files: Sequence[tuple[str, bytes]] | None = None,
        morph_profile_expected_fingerprint: str | None = None,
        require_reversible_history: bool = False,
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
            if (
                expected_geometry_layer_revision is not None
                and session.geometry_layer_revision
                != int(expected_geometry_layer_revision)
            ):
                raise RuntimeError(
                    "Prepared mesh replacement geometry layers are stale: "
                    f"expected revision {int(expected_geometry_layer_revision)}, "
                    f"current revision {session.geometry_layer_revision}."
                )
            if (
                expected_morph_session_revision is not None
                and session.morph_session_revision
                != int(expected_morph_session_revision)
            ):
                raise RuntimeError(
                    "Prepared mesh replacement Morph & Refit state is stale: "
                    f"expected revision {int(expected_morph_session_revision)}, "
                    f"current revision {session.morph_session_revision}."
                )

            if morph_session_state is not None and not isinstance(
                morph_session_state,
                _MeshMorphSessionState,
            ):
                raise TypeError("morph_session_state must be a captured Mesh Morph session state")

            options = _ReplacementOptions(
                history_action=history_action,
                history_label=history_label,
                geometry_layers=geometry_layers,
                active_geometry_layer_id=active_geometry_layer_id,
                geometry_layer_copy_counter=geometry_layer_copy_counter,
                object_transform=object_transform,
                output_policy=output_policy,
                output_destination=output_destination,
                output_destination_ready=output_destination_ready,
                morph_session_state=morph_session_state,
                morph_profile_root=morph_profile_root,
                morph_profile_root_existed=morph_profile_root_existed,
                morph_profile_files=morph_profile_files,
                morph_profile_after_root_existed=morph_profile_after_root_existed,
                morph_profile_after_files=morph_profile_after_files,
                morph_profile_expected_fingerprint=morph_profile_expected_fingerprint,
                require_reversible_history=require_reversible_history,
            )
            history_snapshot = self._capture_replacement_history(session, prepared, options)
            old_undo = list(session.undo_stack)
            old_redo = list(session.redo_stack)
            old_geometry_layers = session.geometry_layers
            old_active_geometry_layer_id = session.active_geometry_layer_id
            old_geometry_layer_copy_counter = session.geometry_layer_copy_counter
            old_geometry_layer_revision = session.geometry_layer_revision
            old_output_policy = session.output_policy
            old_output_destination = session.output_destination
            old_output_destination_ready = session.output_destination_ready
            old_morph_session_revision = session.morph_session_revision
            removed_after_commit: list[_MeshHistorySnapshot] = []
            try:
                next_undo: list[_MeshHistorySnapshot] = []
                for snapshot in old_undo:
                    if snapshot.native_editor_history:
                        removed_after_commit.append(snapshot)
                    else:
                        next_undo.append(snapshot)
                removed_after_commit.extend(old_redo)
                next_undo.append(history_snapshot)
                next_redo: list[_MeshHistorySnapshot] = []
                max_count = max(1, int(self.max_history or 1))
                max_bytes = max(0, int(self.max_history_bytes or 0))
                while next_undo or next_redo:
                    retained = int(
                        _service_call("_history_stack_retained_bytes", next_undo)
                    ) + int(_service_call("_history_stack_retained_bytes", next_redo))
                    if len(next_undo) + len(next_redo) <= max_count and retained <= max_bytes:
                        break
                    trim_stack = next_undo if next_undo else next_redo
                    removed_after_commit.append(trim_stack.pop(0))
                if require_reversible_history and not any(
                    snapshot is history_snapshot for snapshot in next_undo
                ):
                    raise RuntimeError(
                        "Edit Session cannot be committed because its reversible history "
                        "entry would be evicted immediately."
                    )
            except Exception:
                _service_call("_dispose_history_snapshot", history_snapshot)
                raise
            try:
                _service_call("_close_native_editor_session", session)
            except Exception:
                _service_call("_dispose_history_snapshot", history_snapshot)
                raise
            checkpoint = _ReplacementCheckpoint(old_undo, old_redo, old_geometry_layers, old_active_geometry_layer_id, old_geometry_layer_copy_counter, old_geometry_layer_revision, old_output_policy, old_output_destination, old_output_destination_ready, old_morph_session_revision)
            committed_view = self._publish_replacement_with_rollback(session, prepared, history_snapshot, next_undo, next_redo, options, checkpoint)
            disposed: set[int] = set()
            for snapshot in removed_after_commit:
                if id(snapshot) in disposed:
                    continue
                disposed.add(id(snapshot))
                try:
                    _service_call("_dispose_history_snapshot", snapshot)
                except Exception as exc:
                    session.mesh_layer_autosave_error = f"{type(exc).__name__}: {exc}"
            if geometry_layers is not None:
                try:
                    self._schedule_mesh_layer_autosave(session)
                except Exception as exc:
                    session.mesh_layer_autosave_error = f"{type(exc).__name__}: {exc}"
            return committed_view


__all__ = ["MeshWorkingReplacementServiceMixin"]
