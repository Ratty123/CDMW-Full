"""Resident procedural morph/refit authority for :class:`MeshService`."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from pathlib import Path
import sys
import threading
import time
from typing import Mapping, Sequence
from uuid import uuid4

from cdmw.domain.mesh import (
    MeshEditCommand,
    MeshEditResult,
    MeshEditSelection,
    MeshMorphDefinition,
    MeshMorphProfile,
    MeshMorphRule,
    MeshMorphState,
    MeshMorphValuePreset,
    MeshRefitBindingSummary,
    MeshRefitDriverRegion,
    MeshRefitGarmentSettings,
    MeshRefitIslandSettings,
    MeshRefitReferenceBodySummary,
    build_weighted_morph_selection,
    clamp_morph_value,
    generate_morph_fields,
    validate_morph_definition_geometry,
    mesh_morph_driver_topology_fingerprint,
    procedural_morph_pivot,
)
from cdmw.domain.mesh.operations import mesh_edit_operations_from_dicts
from cdmw.modding.mesh_native_core import (
    _native_preview_delta_output_dir,
    create_native_mesh_editor_morph_runtime_snapshot,
    dispose_native_mesh_editor_morph_runtime_snapshot,
    last_native_mesh_core_job_error,
    native_mesh_core_available,
    native_mesh_editor_session_command,
    native_mesh_editor_session_preview_triangle_groups,
    native_mesh_editor_session_preview_vertex_update_groups,
    open_native_mesh_editor_session,
    restore_native_mesh_editor_morph_runtime_snapshot,
)
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.services.mesh_morph_profiles import (
    delete_mesh_morph_preset,
    delete_mesh_morph_profile,
    list_mesh_morph_presets,
    list_mesh_morph_profiles,
    mesh_morph_profile_root,
    read_mesh_morph_bundle,
    save_mesh_morph_preset,
    save_mesh_morph_profile,
    mesh_morph_preset_file_data,
    mesh_morph_profile_file_data,
    save_mesh_morph_bundle,
)
from cdmw.services.mesh_service_history import (
    _active_native_history_indices,
    _dispose_history_snapshot_without_state_failure,
    _validated_mesh_morph_profile_files,
)
from cdmw.services.mesh_service_kernel import _apply_native_editor_dirty_counts
from cdmw.services.mesh_service_payloads import _native_editor_metrics
from cdmw.services.mesh_service_reports import (
    _native_editor_dirty_counts_from_report,
    _native_editor_report_affected_indices,
    _native_editor_report_changed_vertices,
)
from cdmw.services.mesh_service_native_clone import _clone_mesh_for_service_native_snapshot
from cdmw.services.mesh_service_morph_authoring import (
    MeshMorphAuthoringMixin,
    _MorphAuthoringBaseline,
    _MorphCorrectionCapture,
    _profile_role_indices,
    _refit_masks_from_report,
    _refit_settings_batch_payload,
    clone_authoring_baseline,
    clone_correction_capture,
)
from cdmw.services.mesh_service_morph_recipes import MeshMorphRecipeMixin
from cdmw.services.mesh_service_morph_layers import MeshMorphLayerMixin, clear_morph_layers
from cdmw.services.mesh_service_state import (
    _MeshEditSession,
    _MeshHistorySnapshot,
    _MeshMorphSessionState,
)


_REFIT_SETTING_UNSET = object()


@dataclass(slots=True)
class _MeshMorphSessionData:
    profile: MeshMorphProfile | None = None
    preset_id: str = ""
    diagnostics: tuple[str, ...] = ()
    state: MeshMorphState | None = None
    known_profiles: dict[str, MeshMorphProfile] = field(default_factory=dict)
    known_presets: dict[tuple[str, str], MeshMorphValuePreset] = field(default_factory=dict)
    available_profile_ids: tuple[str, ...] = ()
    profile_diagnostics: tuple[str, ...] = ()
    profiles_loaded: bool = False
    profiles_frozen: bool = False
    topology_mesh: object | None = None
    topology_invalidated: bool = False
    authoring_baseline: _MorphAuthoringBaseline | None = None
    correction_capture: _MorphCorrectionCapture | None = None
    authoring_operation: bool = False
    manual_values: dict[str, float] | None = None
    macro_values: dict[str, float] = field(default_factory=dict)
    symmetry_enabled: bool = False
    corrections_enabled: bool = True
    refit_setup_cache: object | None = None


_DEFERRED_MORPH_DISPOSAL_LOCK = threading.Lock()
_DEFERRED_MORPH_DISPOSALS: list[_MeshMorphSessionState] = []
_MORPH_PROFILE_LOCKS_GUARD = threading.Lock()
_MORPH_PROFILE_LOCKS: dict[str, threading.RLock] = {}

def mesh_morph_profile_lock(root: Path | str) -> threading.RLock:
    """Return the process-wide lock for one settings-owned profile tree."""

    key = str(Path(root).expanduser().resolve(strict=False)).casefold()
    with _MORPH_PROFILE_LOCKS_GUARD:
        lock = _MORPH_PROFILE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _MORPH_PROFILE_LOCKS[key] = lock
        return lock


def _service_call(name: str, *args: object, **kwargs: object) -> object:
    return getattr(sys.modules["cdmw.services.mesh_service"], name)(*args, **kwargs)


def _dispose_mesh_morph_session_state_once(state: _MeshMorphSessionState) -> bool:
    snapshot = state.native_snapshot
    if snapshot is None:
        state.retained_bytes = 0
        return True
    try:
        disposed = dispose_native_mesh_editor_morph_runtime_snapshot(snapshot)
    except Exception:
        disposed = False
    if not disposed:
        raw_path = str(snapshot.get("path") or "") if isinstance(snapshot, Mapping) else ""
        if raw_path and not Path(raw_path).exists():
            disposed = True
    if disposed:
        state.native_snapshot = None
        state.retained_bytes = 0
    return bool(disposed)


def retry_deferred_mesh_morph_session_state_disposals() -> int:
    """Retry owned temp-file cleanup without changing editor state."""

    with _DEFERRED_MORPH_DISPOSAL_LOCK:
        pending = list(_DEFERRED_MORPH_DISPOSALS)
        _DEFERRED_MORPH_DISPOSALS.clear()
    remaining: list[_MeshMorphSessionState] = []
    for state in pending:
        if not _dispose_mesh_morph_session_state_once(state):
            remaining.append(state)
    if remaining:
        with _DEFERRED_MORPH_DISPOSAL_LOCK:
            _DEFERRED_MORPH_DISPOSALS.extend(remaining)
    return len(remaining)


def defer_mesh_morph_session_state_disposal(state: _MeshMorphSessionState) -> None:
    """Retain cleanup evidence for retry after semantic publication."""

    if state.native_snapshot is None:
        state.retained_bytes = 0
        return
    with _DEFERRED_MORPH_DISPOSAL_LOCK:
        if all(item is not state for item in _DEFERRED_MORPH_DISPOSALS):
            _DEFERRED_MORPH_DISPOSALS.append(state)


def dispose_mesh_morph_session_state(state: _MeshMorphSessionState) -> None:
    """Release the native file owned by one captured service state."""

    if not isinstance(state, _MeshMorphSessionState):
        raise TypeError("state must be a captured Mesh Morph session state")
    retry_deferred_mesh_morph_session_state_disposals()
    if not _dispose_mesh_morph_session_state_once(state):
        raise RuntimeError("Resident C++ Morph & Refit runtime snapshot cleanup failed.")


from cdmw.services.mesh_service_refit_recovery import MeshRefitRecoveryMixin


class MeshMorphServiceMixin(MeshMorphLayerMixin, MeshMorphAuthoringMixin, MeshMorphRecipeMixin, MeshRefitRecoveryMixin):
    """Keep UI shells thin while the resident C++ session owns deformation."""

    def capture_morph_session_state(self, session_id: str) -> _MeshMorphSessionState:
        """Capture an owned exact runtime snapshot without changing its source."""

        session = self._session(session_id)
        with session.export_lock:
            return self._capture_morph_session_state_locked(session)

    def _capture_morph_session_state_locked(
        self,
        session: _MeshEditSession,
        *,
        preserve_history: bool = False,
    ) -> _MeshMorphSessionState:
        data = self._morph_sessions.get(session.session_id)
        present = isinstance(data, _MeshMorphSessionData)
        history_counts = (
            len(_active_native_history_indices(session.undo_stack)),
            len(_active_native_history_indices(session.redo_stack)),
        ) if preserve_history else None
        if not present and not (history_counts and any(history_counts)):
            return _MeshMorphSessionState(
                present=False,
                session_revision=max(0, int(session.morph_session_revision)),
            )

        self._ensure_native_morph_session_locked(session)
        native_snapshot = create_native_mesh_editor_morph_runtime_snapshot(
            session.session_id,
            **({"history_counts": history_counts} if history_counts is not None else {}),
            timeout_seconds=15.0,
        )
        if native_snapshot is None:
            raise RuntimeError("Resident C++ Morph & Refit runtime snapshot capture failed.")
        try:
            cache = self._clone_morph_session_data(
                data,
                operation="morph.runtime_state_capture",
            ) if present else None
            retained_bytes = int(native_snapshot.get("retained_bytes") or 0)
            if retained_bytes <= 0:
                raise RuntimeError("Resident C++ Morph & Refit runtime snapshot omitted retained bytes.")
            return _MeshMorphSessionState(
                present=present,
                native_snapshot=native_snapshot,
                cache=cache,
                retained_bytes=retained_bytes,
                session_revision=max(0, int(session.morph_session_revision)),
            )
        except Exception:
            if not dispose_native_mesh_editor_morph_runtime_snapshot(native_snapshot):
                raise RuntimeError(
                    "Morph & Refit state capture failed and its temporary runtime snapshot could not be cleaned up."
                )
            raise

    def install_morph_session_state(
        self,
        session_id: str,
        state: _MeshMorphSessionState,
    ) -> MeshMorphState | None:
        """Install a captured runtime onto geometry already present in a target."""

        session = self._session(session_id)
        with session.export_lock:
            return self._install_morph_session_state_locked(session, state)

    def restore_morph_session_cache_after_rejected_edit(
        self,
        session_id: str,
        state: _MeshMorphSessionState,
        *,
        expected_revision: int,
    ) -> None:
        """Restore only Python metadata when native activation was not accepted."""

        session = self._session(session_id)
        with session.export_lock:
            if int(session.morph_session_revision) != int(expected_revision):
                raise RuntimeError(
                    "Morph runtime changed before rejected cache state could be restored."
                )
            if not isinstance(state, _MeshMorphSessionState):
                raise TypeError("state must be a captured Mesh Morph session state")
            if state.present:
                if not isinstance(state.cache, _MeshMorphSessionData):
                    raise ValueError(
                        "Captured Morph & Refit state has no Python session metadata."
                    )
                self._morph_sessions[session.session_id] = state.cache
                state.cache = None
            else:
                if state.cache is not None:
                    raise ValueError(
                        "An absent Morph & Refit state cannot contain Python metadata."
                    )
                self._morph_sessions.pop(session.session_id, None)
            # Do not permit an ABA on the Morph CAS token even though the
            # rejected cache mutation was invisible while export_lock was held.
            session.morph_session_revision = max(
                int(expected_revision),
                max(0, int(state.session_revision)),
            ) + 1

    def _install_morph_session_state_locked(
        self,
        session: _MeshEditSession,
        state: _MeshMorphSessionState,
        *,
        reconcile_profiles: bool = True,
        advance_revision: bool = True,
    ) -> MeshMorphState | None:
        if not isinstance(state, _MeshMorphSessionState):
            raise TypeError("state must be a captured Mesh Morph session state")

        history_only = (
            not state.present and isinstance(state.native_snapshot, Mapping)
            and state.native_snapshot.get("history_captured") is True
        )
        if not state.present and not history_only:
            if state.native_snapshot is not None or state.cache is not None or state.retained_bytes != 0:
                raise ValueError("An absent Morph & Refit state cannot contain runtime data.")
            if session.native_editor_mesh_dirty and not _service_call(
                "_sync_native_editor_session_to_working_mesh",
                session,
            ):
                raise RuntimeError("Resident C++ mesh export failed before clearing Morph & Refit state.")
            self._morph_sessions.pop(session.session_id, None)
            if session.native_editor_session_ready:
                _service_call("_close_native_editor_session", session)
            if advance_revision:
                session.morph_session_revision += 1
            return None

        if not isinstance(state.native_snapshot, Mapping):
            raise ValueError("Captured Morph & Refit state has no native runtime snapshot.")
        if (state.present and not isinstance(state.cache, _MeshMorphSessionData)) or (
            history_only and state.cache is not None
        ):
            raise ValueError("Captured Morph & Refit state has no Python session metadata.")
        try:
            snapshot_retained_bytes = int(state.native_snapshot.get("retained_bytes") or 0)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError("Captured Morph & Refit state has invalid retained-byte evidence.") from exc
        if state.retained_bytes <= 0 or state.retained_bytes != snapshot_retained_bytes:
            raise ValueError("Captured Morph & Refit retained-byte evidence does not match its native snapshot.")

        # Restoring runtime intentionally does not recompose vertices. Make the
        # target's current, already-deformed geometry authoritative first.
        if session.native_editor_mesh_dirty and not _service_call(
            "_sync_native_editor_session_to_working_mesh",
            session,
        ):
            raise RuntimeError("Resident C++ mesh export failed before restoring Morph & Refit state.")

        cache = self._clone_morph_session_data(
            state.cache,
            operation="morph.runtime_state_install",
        ) if state.present else None
        if cache is not None:
            cache.profiles_loaded = self.settings is None or not reconcile_profiles
            cache.available_profile_ids = (
                tuple(sorted(cache.known_profiles))
                if self.settings is None or not reconcile_profiles
                else ()
            )
        previous_cache = self._morph_sessions.get(session.session_id)
        native_ready_before = session.native_editor_session_ready
        if cache is not None:
            self._morph_sessions[session.session_id] = cache
        try:
            # Reconcile persisted profiles before resident runtime changes, but
            # keep the captured unsaved profile in the merged cache.
            if cache is not None and self.settings is not None and reconcile_profiles:
                self._profiles_locked(session, refresh_topology=False)
            self._ensure_native_morph_session_locked(session)
            report = restore_native_mesh_editor_morph_runtime_snapshot(
                session.session_id,
                state.native_snapshot,
                timeout_seconds=15.0,
            )
            if (
                not isinstance(report, Mapping)
                or str(report.get("status") or "").strip().lower() != "ok"
                or report.get("geometry_recomposed") is not False
            ):
                if isinstance(report, Mapping):
                    reason = str(report.get("error") or report.get("message") or report.get("reason") or
                                 f"Unexpected restore response: status={report.get('status')!r}, "
                                 f"geometry_recomposed={report.get('geometry_recomposed')!r}")
                else:
                    reason = last_native_mesh_core_job_error() or "Native restore returned no report or rejection reason."
                raise RuntimeError(f"Resident C++ Morph & Refit runtime snapshot restore failed. {reason}")
        except Exception:
            if previous_cache is None:
                self._morph_sessions.pop(session.session_id, None)
            else:
                self._morph_sessions[session.session_id] = previous_cache
            if not native_ready_before and session.native_editor_session_ready:
                _service_call("_close_native_editor_session", session)
            raise

        accepted_revision = int(session.morph_session_revision)
        if advance_revision:
            session.morph_session_revision += 1
        _service_call("_update_native_history_usage", session, _native_editor_metrics(report))
        if history_only:
            self._morph_sessions.pop(session.session_id, None)
            return None
        try:
            return self._remember_morph_state(
                session,
                self._morph_state_from_report_locked(
                    session,
                    report,
                    refresh_profiles=False,
                ),
            )
        except Exception:
            if not advance_revision:
                session.morph_session_revision = max(
                    int(session.morph_session_revision),
                    accepted_revision,
                ) + 1
            raise

    def dispose_morph_session_state(self, state: _MeshMorphSessionState) -> None:
        """Release a captured state after transfer or history eviction."""

        dispose_mesh_morph_session_state(state)

    @staticmethod
    def defer_morph_session_state_disposal(state: _MeshMorphSessionState) -> None:
        """Keep failed owned-snapshot cleanup available for a later retry."""

        defer_mesh_morph_session_state_disposal(state)

    @staticmethod
    def retry_deferred_morph_session_state_disposals() -> int:
        """Retry cleanup without changing any semantic editor state."""

        return retry_deferred_mesh_morph_session_state_disposals()

    def _capture_morph_profile_history_locked(
        self,
        session: _MeshEditSession,
        *,
        action: str,
        label: str,
        include_profile_files: bool = True,
    ) -> _MeshHistorySnapshot:
        root = None
        existed = False
        files = ()
        if include_profile_files:
            root = self._profile_root()
            existed, files, _fingerprint = _service_call(
                "_mesh_morph_profile_directory_state",
                root,
            )
        if session.native_editor_mesh_dirty and not _service_call(
            "_sync_native_editor_session_to_working_mesh",
            session,
        ):
            raise RuntimeError(
                "Resident C++ mesh export failed before Morph profile history capture."
            )
        snapshot = _service_call("_snapshot", session, prefer_native=True)
        try:
            snapshot.morph_session_state = self._capture_morph_session_state_locked(
                session, preserve_history=True,
            )
        except Exception:
            _service_call("_dispose_history_snapshot", snapshot)
            raise
        snapshot.history_action = str(action)
        snapshot.history_label = str(label)
        if root is not None:
            snapshot.morph_profile_root = str(root)
            snapshot.morph_profile_root_existed = bool(existed)
            snapshot.morph_profile_files = tuple(files)
        return snapshot

    def _publish_morph_profile_history_locked(
        self,
        session: _MeshEditSession,
        snapshot: _MeshHistorySnapshot,
        *,
        base_revision: int,
    ) -> None:
        if snapshot.morph_profile_root is None and snapshot.morph_session_state is None:
            raise RuntimeError("Morph profile history has no settings-owned root.")
        if session.native_editor_mesh_dirty and not _service_call(
            "_sync_native_editor_session_to_working_mesh",
            session,
        ):
            raise RuntimeError(
                "Resident C++ mesh export failed before Morph profile history publication."
            )
        if snapshot.morph_profile_root is not None:
            snapshot.morph_profile_expected_fingerprint = _service_call(
                "_mesh_morph_profile_directory_state",
                snapshot.morph_profile_root,
            )[2]
        _service_call("_capture_history_material_state", session, snapshot)
        snapshot.retained_bytes = int(
            _service_call("_history_snapshot_retained_bytes", snapshot)
        )
        next_undo = [*session.undo_stack, snapshot]
        next_redo: list[_MeshHistorySnapshot] = []
        removed = list(session.redo_stack)
        max_count = max(1, int(self.max_history or 1))
        max_bytes = max(0, int(self.max_history_bytes or 0))
        while next_undo or next_redo:
            if len(next_undo) + len(next_redo) == 1:
                break
            retained = int(
                _service_call("_history_stack_retained_bytes", next_undo)
            ) + int(_service_call("_history_stack_retained_bytes", next_redo))
            if (
                len(next_undo) + len(next_redo) <= max_count
                and retained + session.native_history_retained_bytes <= max_bytes
            ):
                break
            trim_stack = next_undo if next_undo else next_redo
            removed.append(trim_stack.pop(0))
        session.undo_stack[:] = next_undo
        session.redo_stack[:] = next_redo
        if session.revision == int(base_revision):
            session.revision += 1
        for discarded in removed:
            try:
                _service_call("_dispose_history_snapshot", discarded)
            except Exception:
                pass

    def _rollback_unpublished_morph_profile_history_locked(
        self,
        session: _MeshEditSession,
        snapshot: _MeshHistorySnapshot,
    ) -> None:
        """Restore a profile transaction that failed before history publication."""

        outcome = None
        try:
            # Export the failed edit before restoring saved geometry. Otherwise
            # runtime installation can copy the still-dirty resident mesh over
            # the snapshot that rollback just restored.
            if session.native_editor_mesh_dirty:
                self._working_mesh_locked(session, clone=False)
            if snapshot.morph_profile_root is not None:
                snapshot.morph_profile_expected_fingerprint = _service_call(
                    "_mesh_morph_profile_directory_state",
                    snapshot.morph_profile_root,
                )[2]
            outcome = self._restore_snapshot_with_morph_locked(session, snapshot)
            if snapshot.morph_session_state is not None:
                session.morph_session_revision = max(
                    0,
                    int(snapshot.morph_session_state.session_revision),
                )
        finally:
            if outcome is not None:
                _service_call("_dispose_history_snapshot", outcome.snapshot)
            _service_call("_dispose_history_snapshot", snapshot)

    @staticmethod
    def _clone_morph_session_data(
        data: _MeshMorphSessionData,
        *,
        operation: str,
    ) -> _MeshMorphSessionData:
        topology_mesh: ParsedMesh | None = None
        if data.topology_mesh is not None:
            if not isinstance(data.topology_mesh, ParsedMesh):
                raise TypeError("Morph & Refit topology cache must be a ParsedMesh.")
            topology_mesh = _clone_mesh_for_service_native_snapshot(
                data.topology_mesh,
                operation,
                "Python Morph & Refit topology clone fallback blocked while native mesh core is available",
            )
        return _MeshMorphSessionData(
            profile=data.profile,
            preset_id=str(data.preset_id),
            diagnostics=tuple(str(item) for item in data.diagnostics),
            state=data.state,
            known_profiles=dict(data.known_profiles),
            known_presets=dict(data.known_presets),
            available_profile_ids=tuple(str(item) for item in data.available_profile_ids),
            profile_diagnostics=tuple(str(item) for item in data.profile_diagnostics),
            profiles_loaded=bool(data.profiles_loaded),
            profiles_frozen=bool(data.profiles_frozen),
            topology_mesh=topology_mesh,
            topology_invalidated=bool(data.topology_invalidated),
            authoring_baseline=clone_authoring_baseline(data.authoring_baseline),
            correction_capture=clone_correction_capture(data.correction_capture),
            manual_values=None if data.manual_values is None else dict(data.manual_values),
            macro_values=dict(data.macro_values),
            symmetry_enabled=bool(data.symmetry_enabled),
            corrections_enabled=bool(data.corrections_enabled),
        )

    def _apply_morph_edit_command_locked(
        self,
        session: _MeshEditSession,
        command: MeshEditCommand,
    ) -> MeshEditResult:
        action = str(command.action or "").strip().lower()
        params = dict(command.params or {})
        selection = command.selection if command.selection is not None else session.selection
        authored_result = self._apply_morph_authoring_command_locked(session, action, params, selection)
        if authored_result is not None:
            return authored_result
        if action != "morph_refresh":
            self._require_no_pending_morph_authoring(session, include_baseline=True)
        if action == "morph_generate_body_controls":
            return self.generate_body_morph_controls(session.session_id)[0]
        if action == "morph_set_macro":
            return self.set_morph_macro(session.session_id, params.get("macro_id"), params.get("value"), phase=params.get("phase", "end"))[0]
        if action == "morph_reset_macros":
            return self.reset_morph_macros(session.session_id)[0]
        if action == "morph_set_symmetry":
            return self.set_morph_symmetry(session.session_id, params.get("enabled"))[0]
        if action == "morph_set_side_value":
            return self.set_morph_side_value(session.session_id, params.get("pair_id"), params.get("value"), side=params.get("side", "both"), phase=params.get("phase", "end"))[0]
        if action == "morph_refresh":
            self.morph_state(session.session_id)
            return self._result(session, action)
        if action == "morph_activate":
            return self.activate_morph_profile(session.session_id, params.get("profile_id"))[0]
        if action == "morph_author_definition":
            _profile, activation = self.author_morph_definition(
                session.session_id,
                selection=command.selection,
                **{key: value for key, value in params.items() if key != "stop_event"},
            )
            return activation[0]
        if action == "morph_delete_definition":
            return self.delete_morph_definition(session.session_id, params.get("definition_id"))[0]
        if action == "morph_save_profile":
            self.save_active_morph_profile(session.session_id)
            return self._result(session, action)
        if action == "morph_delete_profile":
            deleted, result = self._delete_morph_profile_locked(session, params.get("profile_id"))
            return result if result is not None else self._result(session, action, status="ok" if deleted else "noop")
        if action == "morph_change":
            return self.set_morph_value(
                session.session_id,
                params.get("definition_id"),
                params.get("value"),
                phase=params.get("phase", "end"),
                change_id=params.get("change_id", ""),
            )[0]
        if action == "morph_apply_preset":
            return self.apply_morph_preset(session.session_id, params.get("preset_id"))[0]
        if action == "morph_save_preset":
            self.save_morph_preset(session.session_id, params.get("preset_id"), params.get("name"))
            return self._result(session, action)
        if action == "morph_delete_preset":
            deleted = self.delete_morph_preset(session.session_id, params.get("preset_id"))
            return self._result(session, action, status="ok" if deleted else "noop")
        if action == "morph_set_driver":
            indices = params.get("submesh_indices") or selection.source_indices
            return self.set_refit_driver(session.session_id, tuple(indices or ()))[0]  # type: ignore[arg-type]
        if action == "morph_bind":
            indices = params.get("garment_submesh_indices") or selection.source_indices
            return self.bind_refit(session.session_id, tuple(indices or ()))[0]  # type: ignore[arg-type]
        if action == "morph_configure_refit":
            indices = params.get("garment_submesh_indices") or selection.source_indices
            return self.configure_refit(
                session.session_id,
                tuple(indices or ()),  # type: ignore[arg-type]
                **{key: params[key] for key in (
                    "enabled", "intensity_percent", "mode", "clearance_percent", "tightness_percent",
                ) if key in params},
            )[0]
        if action == "morph_set_reference_body":
            reference = params.get("reference_body")
            if reference is None:
                return self.clear_refit_reference_body(session.session_id)[0]
            return self.fit_refit_to_reference_body(session.session_id, reference)[0]
        if action == "morph_clear_refit":
            return self.clear_refit(session.session_id)[0]
        if action == "morph_reset":
            return self.reset_morph(session.session_id)[0]
        if action == "morph_bake":
            return self.bake_morph(session.session_id)[0]
        if action == "morph_finish":
            return self.finish_morph(session.session_id)[0]
        raise ValueError(f"Unsupported procedural morph action: {action}")

    def morph_state(self, session_id: str) -> MeshMorphState:
        session = self._session(session_id)
        with session.export_lock:
            report = self._run_morph_query_locked(session, "morph_state")
            return self._remember_morph_state(
                session,
                self._morph_state_from_report_locked(session, report, refresh_profiles=True),
            )

    def prime_morph_profile_cache(
        self,
        session_id: str,
        *,
        freeze: bool = False,
    ) -> None:
        """Load the complete profile/preset tree before a Rust helper starts."""

        session = self._session(session_id)
        with session.export_lock, mesh_morph_profile_lock(self._profile_root()):
            profiles, diagnostics = self._profiles_locked(
                session,
                refresh_topology=True,
            )
            data = self._morph_sessions.get(session.session_id)
            if not isinstance(data, _MeshMorphSessionData):
                data = _MeshMorphSessionData()
                self._morph_sessions[session.session_id] = data
            data.known_presets.clear()
            preset_diagnostics: list[str] = []
            for profile in profiles:
                presets, current_diagnostics = list_mesh_morph_presets(
                    self._profile_root(),
                    profile,
                )
                preset_diagnostics.extend(current_diagnostics)
                for preset in presets:
                    data.known_presets[(profile.profile_id, preset.preset_id)] = preset
            data.diagnostics = tuple(
                dict.fromkeys((*data.diagnostics, *diagnostics, *preset_diagnostics))
            )
            data.profiles_frozen = bool(freeze)

    def cached_morph_state_from_runtime(self, session_id: str) -> MeshMorphState:
        """Query resident values without rereading helper-visible profile files."""

        session = self._session(session_id)
        with session.export_lock:
            report = self._run_morph_query_locked(session, "morph_state")
            return self._remember_morph_state(
                session,
                self._morph_state_from_report_locked(
                    session,
                    report,
                    refresh_profiles=False,
                    refresh_presets=False,
                ),
            )

    def set_morph_profile_cache_frozen(
        self,
        session_id: str,
        frozen: bool,
    ) -> None:
        session = self._session(session_id)
        with session.export_lock:
            data = self._morph_sessions.get(session.session_id)
            if isinstance(data, _MeshMorphSessionData):
                data.profiles_frozen = bool(frozen)

    def cached_morph_state(self, session_id: str) -> MeshMorphState | None:
        session = self._session(session_id)
        with session.export_lock:
            data = self._morph_sessions.get(session.session_id)
            return data.state if isinstance(data, _MeshMorphSessionData) else None

    def activate_morph_profile(self, session_id: str, profile_id: object) -> tuple[MeshEditResult, MeshMorphState]:
        session = self._session(session_id)
        with session.export_lock:
            profiles, diagnostics = self._profiles_locked(session, refresh_topology=True)
            requested = str(profile_id or "").strip()
            profile = next((item for item in profiles if item.profile_id == requested), None)
            if profile is None:
                raise ValueError(f"Unknown procedural morph profile: {requested or '<empty>'}")
            return self._activate_morph_profile_locked(session, profile, diagnostics)

    def activate_cached_morph_profile(
        self,
        session_id: str,
        profile_id: object,
    ) -> tuple[MeshEditResult, MeshMorphState]:
        """Activate only a profile captured before the Rust helper launched."""

        session = self._session(session_id)
        with session.export_lock:
            data = self._morph_sessions.get(session.session_id)
            requested = str(profile_id or "").strip()
            profile = (
                data.known_profiles.get(requested)
                if isinstance(data, _MeshMorphSessionData)
                else None
            )
            if profile is None:
                raise ValueError(
                    f"Unknown cached procedural morph profile: {requested or '<empty>'}"
                )
            return self._activate_morph_profile_locked(
                session,
                profile,
                tuple(data.diagnostics),
            )

    def _activate_morph_profile_locked(
        self,
        session: _MeshEditSession,
        profile: MeshMorphProfile,
        diagnostics: tuple[str, ...] = (),
        *,
        record_history: bool = True,
        preserve_runtime: bool = False,
        neutral_positions: Sequence[Mapping[str, object]] | None = None,
        values: Mapping[str, float] | None = None,
        base_mesh: ParsedMesh | None = None,
        retain_layers: bool = False,
    ) -> tuple[MeshEditResult, MeshMorphState]:
        current_data = self._morph_sessions.get(session.session_id)
        if record_history and current_data is not None and current_data.manual_values is not None:
            self._require_no_pending_morph_authoring(session, include_baseline=True)
            return self._morph_authoring_transaction_locked(
                session, "morph_activate", "Select Morph Profile",
                lambda: self._activate_morph_profile_locked(
                    session, profile, diagnostics, record_history=False,
                    preserve_runtime=preserve_runtime, neutral_positions=neutral_positions,
                    values=values, base_mesh=base_mesh, retain_layers=retain_layers,
                )[0],
            )
        driver_mesh = base_mesh if base_mesh is not None else self._profile_driver_mesh_locked(session)
        if base_mesh is None and any(item.source_kind == "authored" or item.garment_corrections for item in profile.definitions):
            driver_mesh = self._native_neutral_mesh_locked(session, _profile_role_indices(profile))
        current_fingerprint = mesh_morph_driver_topology_fingerprint(driver_mesh, profile.definitions)
        if profile.topology_fingerprint != current_fingerprint:
            raise RuntimeError("Procedural morph profile topology does not match the active Edit Mesh driver.")
        fields = [
            (sparse, stage)
            for definition in profile.definitions
            for stage, rows in (
                ("base", generate_morph_fields(driver_mesh, definition)),
                ("post_refit", definition.garment_corrections),
            )
            for sparse in rows
            if stage != "post_refit" or current_data is None or current_data.corrections_enabled
        ]
        upload_payload = {
            "profile": {
                "profile_id": profile.profile_id,
                "name": profile.name,
                "topology_fingerprint": profile.topology_fingerprint,
                "definitions": [
                    {
                        "definition_id": definition.definition_id,
                        "label": definition.label,
                        "category": definition.category,
                        "min_percent": definition.min_percent,
                        "max_percent": definition.max_percent,
                        "default_percent": definition.default_percent,
                    }
                    for definition in profile.definitions
                ],
                "fields": [
                    {
                        "definition_id": sparse.definition_id,
                        "submesh_index": sparse.submesh_index,
                        "vertex_indices": sparse.vertex_indices,
                        "deltas": sparse.deltas,
                        "stage": stage,
                    }
                    for sparse, stage in fields
                ],
            }
        }
        if preserve_runtime:
            upload_payload["preserve_runtime"] = True
        if neutral_positions is not None:
            upload_payload["neutral_positions"] = list(neutral_positions)
        if values is not None:
            upload_payload["values"] = dict(values)
        report = self._run_morph_command_locked(
            session,
            "morph_upload",
            upload_payload,
            history_label="Select Morph Profile",
            record_history=record_history,
        )
        data = self._morph_sessions.get(session.session_id)
        if not isinstance(data, _MeshMorphSessionData):
            data = _MeshMorphSessionData()
            self._morph_sessions[session.session_id] = data
        data.profile = profile
        if not retain_layers:
            clear_morph_layers(data)
        data.preset_id = ""
        data.diagnostics = tuple(diagnostics)
        data.known_profiles[profile.profile_id] = profile
        data.available_profile_ids = tuple(dict.fromkeys((*data.available_profile_ids, profile.profile_id)))
        data.topology_invalidated = False
        if base_mesh is not None or any(item.source_kind == "authored" or item.garment_corrections for item in profile.definitions):
            data.topology_mesh = driver_mesh
        return self._morph_result_and_state_locked(session, "morph_upload", report)

    def author_morph_definition(
        self,
        session_id: str,
        *,
        selection: MeshEditSelection | None = None,
        **definition: object,
    ) -> tuple[MeshMorphProfile, tuple[MeshEditResult, MeshMorphState]]:
        """Create and activate a definition with its original cache in history."""
        session = self._session(session_id)
        with session.export_lock, mesh_morph_profile_lock(self._profile_root()):
            self._require_baked_morph_definition_edit(session)
            history = self._capture_morph_profile_history_locked(
                session, action="morph_author_definition", label="Edit slider",
            )
            base_revision = session.revision
            activation_base_revision: int | None = None
            try:
                if selection is not None:
                    session.selection = selection
                profile = self.create_morph_definition(session_id, **definition)
                data = self._required_morph_data(session)
                activation_base_revision = int(session.morph_session_revision)
                result, state = self._activate_morph_profile_locked(
                    session, profile, data.diagnostics, record_history=False,
                )
                self._publish_morph_profile_history_locked(
                    session, history, base_revision=base_revision,
                )
            except Exception as command_error:
                failed_revision = int(session.morph_session_revision)
                native_activation_accepted = (
                    activation_base_revision is not None
                    and failed_revision != activation_base_revision
                )
                try:
                    if native_activation_accepted:
                        self._rollback_unpublished_morph_profile_history_locked(session, history)
                    else:
                        # A rejected definition or upload preflight has not changed
                        # the resident cursor. Restore only its Python metadata.
                        try:
                            if history.morph_session_state is not None:
                                self.restore_morph_session_cache_after_rejected_edit(
                                    session_id, history.morph_session_state,
                                    expected_revision=int(session.morph_session_revision),
                                )
                            session.selection = history.selection
                        finally:
                            _dispose_history_snapshot_without_state_failure(history)
                except Exception as rollback_error:
                    raise RuntimeError(
                        "Morph definition creation failed and its runtime rollback also failed."
                    ) from rollback_error
                finally:
                    if native_activation_accepted:
                        # The rollback snapshot must not restore a reusable CAS token.
                        session.morph_session_revision = max(
                            int(session.morph_session_revision), failed_revision,
                        ) + 1
                        # Runtime restoration clears the resident history cursor.
                        # Retain unrelated Python snapshots, never stale markers.
                        discarded = []
                        for stack in (session.undo_stack, session.redo_stack):
                            retained = []
                            for snapshot in stack:
                                if snapshot.native_editor_history:
                                    discarded.append(snapshot)
                                else:
                                    retained.append(snapshot)
                            stack[:] = retained
                        session.native_history_undo_count = 0
                        session.native_history_redo_count = 0
                        session.native_history_retained_bytes = 0
                        disposed: set[int] = set()
                        for snapshot in discarded:
                            if id(snapshot) not in disposed:
                                disposed.add(id(snapshot))
                                _dispose_history_snapshot_without_state_failure(snapshot)
                raise command_error
            state = replace(state, edit_revision=session.revision)
            self._required_morph_data(session).state = state
            return profile, (replace(result, revision=session.revision), state)

    def create_morph_definition(
        self,
        session_id: str,
        *,
        profile_id: object,
        profile_name: object,
        definition_id: object,
        label: object,
        category: object = "General",
        rule: object = "volume",
        axis: object = "y",
        amount: object = 0.1,
        feather: object = 2,
        falloff: object = "smooth",
        mirror_mode: object = "off",
        min_percent: object = -100.0,
        max_percent: object = 100.0,
        default_percent: object = 0.0,
        local_basis: Sequence[Sequence[object]] = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        preserve_selection: object = False,
        source_definition_id: object = "",
    ) -> MeshMorphProfile:
        session = self._session(session_id)
        with session.export_lock:
            self._require_baked_morph_definition_edit(session)
            mesh = self._working_mesh_locked(session, clone=False)
            requested_profile_id = str(profile_id or "").strip() or f"profile-{uuid4().hex[:10]}"
            requested_definition_id = str(definition_id or "").strip()
            original_definition_id = str(source_definition_id or requested_definition_id).strip()
            data = self._morph_sessions.get(session.session_id)
            profiles, _diagnostics = self._profiles_locked(session, refresh_topology=True)
            existing = (
                data.profile
                if isinstance(data, _MeshMorphSessionData)
                and data.profile is not None
                and data.profile.profile_id == requested_profile_id
                else next((item for item in profiles if item.profile_id == requested_profile_id), None)
            )
            existing_definition = next(
                (
                    item
                    for item in (existing.definitions if existing is not None else ())
                    if item.definition_id == original_definition_id
                ),
                None,
            )
            if existing_definition is not None and existing_definition.source_kind == "authored":
                raise ValueError("Sculpted sliders must be changed by capturing a new target.")
            preserve_existing_selection = preserve_selection is True or str(preserve_selection).strip().lower() in {"1", "true", "yes", "on"}
            if preserve_existing_selection:
                if existing_definition is None:
                    raise ValueError(f"Unknown procedural morph definition: {original_definition_id or '<empty>'}")
                weighted = existing_definition.vertices
                pivot = existing_definition.pivot
                definition_basis = existing_definition.local_basis
            else:
                selected_sets = {
                    submesh_index: set(vertex_indices)
                    for submesh_index, vertex_indices in session.selection.vertex_map().items()
                    if 0 <= submesh_index < len(mesh.submeshes)
                }
                for submesh_index, edges in session.selection.edge_map().items():
                    if not 0 <= submesh_index < len(mesh.submeshes):
                        continue
                    vertices = selected_sets.setdefault(submesh_index, set())
                    for edge in edges:
                        vertices.update(int(vertex) for vertex in tuple(edge)[:2])
                for submesh_index, face_indices in session.selection.face_map().items():
                    if not 0 <= submesh_index < len(mesh.submeshes):
                        continue
                    submesh = mesh.submeshes[submesh_index]
                    vertices = selected_sets.setdefault(submesh_index, set())
                    for face_index in face_indices:
                        if 0 <= face_index < len(submesh.faces):
                            vertices.update(int(vertex) for vertex in tuple(submesh.faces[face_index])[:3])
                for source_index in session.selection.source_indices:
                    if 0 <= source_index < len(mesh.submeshes):
                        selected_sets[source_index] = set(range(len(mesh.submeshes[source_index].vertices)))
                selected = {
                    submesh_index: tuple(sorted(
                        vertex_index
                        for vertex_index in vertex_indices
                        if 0 <= vertex_index < len(mesh.submeshes[submesh_index].vertices)
                    ))
                    for submesh_index, vertex_indices in selected_sets.items()
                }
                selected = {submesh_index: vertices for submesh_index, vertices in selected.items() if vertices}
                if not selected:
                    raise ValueError("Select mesh vertices or choose at least one part before creating a Morph profile slider.")
                weighted = build_weighted_morph_selection(
                    mesh,
                    selected,
                    feather=max(0, int(feather)),
                    falloff=str(falloff or "smooth"),
                    mirror_mode=str(mirror_mode or "off"),
                )
                pivot = procedural_morph_pivot(mesh, weighted)
                definition_basis = tuple(tuple(float(value) for value in basis[:3]) for basis in local_basis)
            definition = MeshMorphDefinition(
                definition_id=requested_definition_id,
                label=str(label or "").strip(),
                category=str(category or "General").strip(),
                vertices=weighted,
                pivot=pivot,
                local_basis=definition_basis,  # type: ignore[arg-type]
                rule=MeshMorphRule(
                    kind=str(rule or "volume"),
                    axis=str(axis or "y"),
                    amount=float(amount),
                    falloff=str(falloff or "smooth"),
                    feather=max(0, int(feather)),
                ),
                mirror_mode=str(mirror_mode or "off"),
                min_percent=float(min_percent),
                max_percent=float(max_percent),
                default_percent=float(default_percent),
            )
            if existing_definition is not None and existing_definition.garment_corrections:
                definition = replace(
                    definition,
                    garment_corrections=tuple(
                        replace(field, definition_id=definition.definition_id)
                        for field in existing_definition.garment_corrections
                    ),
                    correction_topology_fingerprint=existing_definition.correction_topology_fingerprint,
                    correction_base_geometry_fingerprint=existing_definition.correction_base_geometry_fingerprint,
                )
                neutral = self._native_neutral_mesh_locked(
                    session,
                    tuple(field.submesh_index for field in definition.garment_corrections),
                )
                validate_morph_definition_geometry(neutral, definition)
            definitions = [
                item
                for item in (existing.definitions if existing is not None else ())
                if item.definition_id not in {original_definition_id, definition.definition_id}
            ]
            definitions.append(definition)
            profile = MeshMorphProfile(
                profile_id=requested_profile_id,
                name=str(profile_name or (existing.name if existing is not None else requested_profile_id)).strip(),
                topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, definitions),
                definitions=tuple(definitions),
            )
            if not isinstance(data, _MeshMorphSessionData):
                data = _MeshMorphSessionData()
                self._morph_sessions[session.session_id] = data
            data.profile = profile
            data.known_profiles[profile.profile_id] = profile
            data.available_profile_ids = tuple(dict.fromkeys((*data.available_profile_ids, profile.profile_id)))
            data.topology_mesh = mesh
            data.topology_invalidated = False
            session.morph_session_revision += 1
            return profile

    def delete_morph_definition(
        self,
        session_id: str,
        definition_id: object,
    ) -> tuple[MeshEditResult, MeshMorphState]:
        session = self._session(session_id)
        with session.export_lock:
            self._require_baked_morph_definition_edit(session)
            data = self._required_morph_data(session)
            key = str(definition_id or "").strip()
            definitions = tuple(
                definition
                for definition in data.profile.definitions  # type: ignore[union-attr]
                if definition.definition_id != key
            )
            if len(definitions) == len(data.profile.definitions):  # type: ignore[union-attr]
                raise ValueError(f"Unknown procedural morph definition: {key or '<empty>'}")
            driver_mesh = self._profile_driver_mesh_locked(session)
            profile = replace(  # type: ignore[arg-type]
                data.profile,
                definitions=definitions,
                topology_fingerprint=mesh_morph_driver_topology_fingerprint(driver_mesh, definitions),
            )
            return self._activate_morph_profile_locked(session, profile, data.diagnostics)

    def save_active_morph_profile(self, session_id: str) -> MeshMorphProfile:
        session = self._session(session_id)
        with session.export_lock, mesh_morph_profile_lock(self._profile_root()):
            data = self._morph_sessions.get(session.session_id)
            if not isinstance(data, _MeshMorphSessionData) or data.profile is None:
                raise RuntimeError("No procedural morph profile is active.")
            history = self._capture_morph_profile_history_locked(
                session,
                action="morph_save_profile",
                label="Save Morph Profile",
            )
            history_base_revision = session.revision
            profile = replace(data.profile, migrated_from_version=0, requires_v2_save=False)
            try:
                save_mesh_morph_profile(self._profile_root(), profile)
                data.profile = profile
                data.known_profiles[profile.profile_id] = profile
                data.available_profile_ids = tuple(dict.fromkeys((*data.available_profile_ids, profile.profile_id)))
                self._refresh_cached_morph_metadata_locked(session)
                session.morph_session_revision += 1
                self._publish_morph_profile_history_locked(
                    session,
                    history,
                    base_revision=history_base_revision,
                )
                return profile
            except Exception:
                self._rollback_unpublished_morph_profile_history_locked(
                    session,
                    history,
                )
                raise

    def delete_morph_profile(self, session_id: str, profile_id: object) -> bool:
        session = self._session(session_id)
        with session.export_lock:
            deleted, _result = self._delete_morph_profile_locked(session, profile_id)
            return deleted

    def _delete_morph_profile_locked(
        self,
        session: _MeshEditSession,
        profile_id: object,
    ) -> tuple[bool, MeshEditResult | None]:
        with mesh_morph_profile_lock(self._profile_root()):
            return self._delete_morph_profile_under_profile_lock(
                session,
                profile_id,
            )

    def _delete_morph_profile_under_profile_lock(
        self,
        session: _MeshEditSession,
        profile_id: object,
    ) -> tuple[bool, MeshEditResult | None]:
        profile_key = str(profile_id or "").strip()
        data = self._morph_sessions.get(session.session_id)
        active_in_memory = bool(
            isinstance(data, _MeshMorphSessionData)
            and data.profile is not None
            and data.profile.profile_id == profile_key
        )
        known_in_memory = bool(
            isinstance(data, _MeshMorphSessionData)
            and profile_key in data.known_profiles
        )
        history = self._capture_morph_profile_history_locked(
            session,
            action="morph_delete_profile",
            label="Delete Morph Profile",
        )
        history_base_revision = session.revision
        try:
            deleted = bool(
                delete_mesh_morph_profile(self._profile_root(), profile_key)
                or active_in_memory
                or known_in_memory
            )
            result: MeshEditResult | None = None
            if active_in_memory and isinstance(data, _MeshMorphSessionData):
                reset_report = self._run_morph_command_locked(
                    session,
                    "morph_reset",
                    {"suppress_history": True},
                    history_label="Reset Morph",
                    record_history=False,
                )
                clear_morph_layers(data)
                result, _state = self._morph_result_and_state_locked(
                    session,
                    "morph_delete_profile",
                    reset_report,
                )
                self._run_morph_command_locked(
                    session,
                    "morph_upload",
                    {"profile": {}, "suppress_history": True},
                    history_label="Clear Morph Profile",
                    record_history=False,
                )
                data.profile = None
                data.preset_id = ""
            if deleted and isinstance(data, _MeshMorphSessionData):
                data.known_profiles.pop(profile_key, None)
                data.known_presets = {
                    key: preset
                    for key, preset in data.known_presets.items()
                    if key[0] != profile_key
                }
                data.available_profile_ids = tuple(
                    item for item in data.available_profile_ids if item != profile_key
                )
                self._refresh_cached_morph_metadata_locked(session)
            if deleted and not active_in_memory:
                session.morph_session_revision += 1
            if deleted:
                self._publish_morph_profile_history_locked(
                    session,
                    history,
                    base_revision=history_base_revision,
                )
            else:
                _service_call("_dispose_history_snapshot", history)
            return deleted, result
        except Exception:
            self._rollback_unpublished_morph_profile_history_locked(
                session,
                history,
            )
            raise

    def set_morph_value(
        self,
        session_id: str,
        definition_id: object,
        value: object,
        *,
        phase: object = "end",
        change_id: object = "",
    ) -> tuple[MeshEditResult, MeshMorphState]:
        session = self._session(session_id)
        with session.export_lock:
            data = self._required_morph_data(session)
            definition_key = str(definition_id or "").strip()
            definition = next((item for item in data.profile.definitions if item.definition_id == definition_key), None)  # type: ignore[union-attr]
            if definition is None:
                raise ValueError(f"Unknown procedural morph definition: {definition_key or '<empty>'}")
            normalized_phase = str(phase or "end").strip().lower()
            if data.manual_values is not None:
                return self._set_layered_manual_value_locked(
                    session, definition, value, phase=normalized_phase,
                )
            report = self._run_morph_command_locked(
                session,
                "morph_change",
                {
                    "definition_id": definition.definition_id,
                    "value": clamp_morph_value(definition, value),
                    "phase": normalized_phase,
                    "change_id": str(change_id or "").strip() or f"morph-{uuid4().hex}",
                },
                history_label=f"Morph {definition.label}",
                record_history=normalized_phase != "cancel",
            )
            return self._morph_result_and_state_locked(session, "morph_change", report)

    def apply_morph_preset(self, session_id: str, preset_id: object) -> tuple[MeshEditResult, MeshMorphState]:
        session = self._session(session_id)
        with session.export_lock:
            data = self._required_morph_data(session)
            with mesh_morph_profile_lock(self._profile_root()):
                presets, diagnostics = list_mesh_morph_presets(
                    self._profile_root(),
                    data.profile,  # type: ignore[arg-type]
                )
            requested = str(preset_id or "").strip()
            preset = next((item for item in presets if item.preset_id == requested), None)
            if preset is None:
                raise ValueError(f"Unknown procedural morph preset: {requested or '<empty>'}")
            if preset.manual_values is not None or data.manual_values is not None:
                return self._apply_layered_morph_preset_locked(session, preset, diagnostics)
            report = self._run_morph_command_locked(
                session,
                "morph_apply_preset",
                {"preset_id": preset.preset_id, "values": {key: value for key, value in preset.values}},
                history_label=f"Apply Morph Preset {preset.name}",
                record_history=True,
            )
            data.preset_id = preset.preset_id
            data.diagnostics = tuple(dict.fromkeys((*data.diagnostics, *diagnostics)))
            return self._morph_result_and_state_locked(session, "morph_apply_preset", report)

    def apply_cached_morph_preset(
        self,
        session_id: str,
        preset_id: object,
    ) -> tuple[MeshEditResult, MeshMorphState]:
        """Apply only a preset captured before the Rust helper launched."""

        session = self._session(session_id)
        with session.export_lock:
            data = self._required_morph_data(session)
            requested = str(preset_id or "").strip()
            preset = data.known_presets.get(
                (data.profile.profile_id, requested),  # type: ignore[union-attr]
            )
            if preset is None:
                raise ValueError(
                    f"Unknown cached procedural morph preset: {requested or '<empty>'}"
                )
            if preset.manual_values is not None or data.manual_values is not None:
                return self._apply_layered_morph_preset_locked(session, preset)
            report = self._run_morph_command_locked(
                session,
                "morph_apply_preset",
                {
                    "preset_id": preset.preset_id,
                    "values": {key: value for key, value in preset.values},
                },
                history_label=f"Apply Morph Preset {preset.name}",
                record_history=True,
            )
            data.preset_id = preset.preset_id
            return self._morph_result_and_state_locked(
                session,
                "morph_apply_preset",
                report,
            )

    def save_morph_preset(self, session_id: str, preset_id: object, name: object) -> MeshMorphValuePreset:
        session = self._session(session_id)
        with session.export_lock, mesh_morph_profile_lock(self._profile_root()):
            data = self._required_morph_data(session)
            history = self._capture_morph_profile_history_locked(
                session,
                action="morph_save_preset",
                label="Save Morph Preset",
            )
            history_base_revision = session.revision
            report = self._run_morph_query_locked(session, "morph_state")
            values = _morph_values_from_report(report)
            preset = MeshMorphValuePreset(
                preset_id=str(preset_id or "").strip(),
                name=str(name or preset_id or "").strip(),
                profile_id=data.profile.profile_id,  # type: ignore[union-attr]
                topology_fingerprint=data.profile.topology_fingerprint,  # type: ignore[union-attr]
                values=tuple(values.items()),
                **self._morph_layer_preset_fields_locked(session),
            )
            try:
                save_mesh_morph_profile(self._profile_root(), data.profile)
                save_mesh_morph_preset(self._profile_root(), preset)
                data.preset_id = preset.preset_id
                data.known_presets[(preset.profile_id, preset.preset_id)] = preset
                self._remember_morph_state(
                    session,
                    self._morph_state_from_report_locked(session, report),
                )
                session.morph_session_revision += 1
                self._publish_morph_profile_history_locked(
                    session,
                    history,
                    base_revision=history_base_revision,
                )
                return preset
            except Exception:
                self._rollback_unpublished_morph_profile_history_locked(
                    session,
                    history,
                )
                raise

    def export_morph_preset(self, session_id: str, path: str, name: str) -> str:
        """Export current values plus their definition without changing library history."""
        destination = Path(path).expanduser().resolve()
        if destination.suffix.lower() != ".json" or not name.strip():
            raise ValueError("Preset export needs a name and a JSON destination")
        session = self._session(session_id)
        with session.export_lock:
            data = self._required_morph_data(session)
            report = self._run_morph_query_locked(session, "morph_state")
            preset = MeshMorphValuePreset(
                preset_id=f"preset-{uuid4().hex[:12]}", name=name.strip(),
                profile_id=data.profile.profile_id,
                topology_fingerprint=data.profile.topology_fingerprint,
                values=tuple(_morph_values_from_report(report).items()),
                **self._morph_layer_preset_fields_locked(session),
            )
            save_mesh_morph_bundle(destination, data.profile, preset)
        return str(destination)

    def import_morph_preset(self, session_id: str, path: str) -> MeshMorphState:
        """Load, validate, preview, and save a portable preset as one undoable edit."""
        session = self._session(session_id)
        with session.export_lock, mesh_morph_profile_lock(self._profile_root()):
            self._require_baked_morph_definition_edit(session)
            profile, preset = read_mesh_morph_bundle(
                path, self._profile_driver_mesh_locked(session),
                max_bytes=None,
            )
            history = self._capture_morph_profile_history_locked(
                session, action="morph_import_preset", label=f"Load Morph Preset {preset.name}",
            )
            base_revision = session.revision
            try:
                files = dict(history.morph_profile_files or ())
                relative, document = mesh_morph_profile_file_data(profile)
                cache = self._morph_sessions.get(session_id)
                existing = cache.known_profiles.get(profile.profile_id) if cache is not None else None
                if (relative in files and files[relative] != document) or (existing is not None and existing != profile):
                    profile = replace(profile, profile_id=f"import-{uuid4().hex[:12]}", name=f"{profile.name} (imported)")
                    preset = replace(preset, profile_id=profile.profile_id)
                relative, document = mesh_morph_preset_file_data(preset)
                if relative in files and files[relative] != document:
                    preset = replace(preset, preset_id=f"import-{uuid4().hex[:12]}")
                for relative, document in (
                    mesh_morph_profile_file_data(profile),
                    mesh_morph_preset_file_data(preset),
                ):
                    files[relative] = document
                _validated_mesh_morph_profile_files(tuple(sorted(files.items())))
            except Exception:
                _service_call("_dispose_history_snapshot", history)
                raise
            try:
                self._activate_morph_profile_locked(session, profile, record_history=False)
                report = self._run_morph_command_locked(
                    session, "morph_apply_preset", {"preset_id": preset.preset_id, "values": dict(preset.values)},
                    history_label=f"Load Morph Preset {preset.name}", record_history=False,
                )
                save_mesh_morph_profile(self._profile_root(), profile)
                save_mesh_morph_preset(self._profile_root(), preset)
                data = self._required_morph_data(session)
                data.preset_id = preset.preset_id
                data.known_presets[(profile.profile_id, preset.preset_id)] = preset
                self._install_morph_preset_layers_locked(session, preset)
                state = self._morph_result_and_state_locked(session, "morph_apply_preset", report)[1]
                self._publish_morph_profile_history_locked(session, history, base_revision=base_revision)
                return state
            except Exception:
                self._rollback_unpublished_morph_profile_history_locked(session, history)
                raise

    def delete_morph_preset(self, session_id: str, preset_id: object) -> bool:
        session = self._session(session_id)
        with session.export_lock, mesh_morph_profile_lock(self._profile_root()):
            data = self._required_morph_data(session)
            history = self._capture_morph_profile_history_locked(
                session,
                action="morph_delete_preset",
                label="Delete Morph Preset",
            )
            history_base_revision = session.revision
            try:
                deleted = delete_mesh_morph_preset(self._profile_root(), data.profile.profile_id, preset_id)  # type: ignore[union-attr]
                if deleted and data.preset_id == str(preset_id or ""):
                    data.preset_id = ""
                if deleted:
                    data.known_presets.pop(
                        (data.profile.profile_id, str(preset_id or "")),  # type: ignore[union-attr]
                        None,
                    )
                if deleted:
                    self._refresh_cached_morph_metadata_locked(session)
                    session.morph_session_revision += 1
                    self._publish_morph_profile_history_locked(
                        session,
                        history,
                        base_revision=history_base_revision,
                    )
                else:
                    _service_call("_dispose_history_snapshot", history)
                return deleted
            except Exception:
                self._rollback_unpublished_morph_profile_history_locked(
                    session,
                    history,
                )
                raise

    def set_refit_driver(self, session_id: str, submesh_indices: Sequence[object]) -> tuple[MeshEditResult, MeshMorphState]:
        driver_indices = _indices(submesh_indices)
        session = self._session(session_id)
        with session.export_lock:
            self._require_baked_morph_definition_edit(session)
            data = self._required_morph_data(session)
            garment_indices = data.state.refit.garment_submesh_indices if data.state is not None else ()
            overlap = tuple(sorted(set(driver_indices).intersection(garment_indices)))
            if overlap:
                raise ValueError(f"Refit driver parts cannot also be garment parts: {', '.join(str(index) for index in overlap)}")
            report = self._run_morph_command_locked(
                session,
                "morph_set_driver",
                {"submesh_indices": driver_indices},
                history_label="Set Refit Driver",
                record_history=True,
            )
            return self._morph_result_and_state_locked(session, "morph_set_driver", report)

    def bind_refit(self, session_id: str, garment_submesh_indices: Sequence[object]) -> tuple[MeshEditResult, MeshMorphState]:
        garment_indices = _indices(garment_submesh_indices)
        session = self._session(session_id)
        with session.export_lock:
            self._require_baked_morph_definition_edit(session)
            data = self._required_morph_data(session)
            driver_indices = data.state.driver_submesh_indices if data.state is not None else ()
            overlap = tuple(sorted(set(garment_indices).intersection(driver_indices)))
            if overlap:
                raise ValueError(f"Garment parts cannot also be refit driver parts: {', '.join(str(index) for index in overlap)}")
            report = self._run_morph_command_locked(
                session,
                "morph_bind",
                {"garment_submesh_indices": garment_indices},
                history_label="Bind Garment Refit",
                record_history=True,
            )
            return self._morph_result_and_state_locked(session, "morph_bind", report)

    def configure_refit(
        self,
        session_id: str,
        garment_submesh_indices: Sequence[object],
        *,
        enabled: object = _REFIT_SETTING_UNSET,
        intensity_percent: object = _REFIT_SETTING_UNSET,
        mode: object = _REFIT_SETTING_UNSET,
        clearance_percent: object = _REFIT_SETTING_UNSET,
        tightness_percent: object = None,
    ) -> tuple[MeshEditResult, MeshMorphState]:
        """Apply only supplied fields to each Part's resident settings, atomically."""
        garment_indices = _indices(garment_submesh_indices)
        if not garment_indices:
            raise ValueError("Refit settings require at least one bound garment part.")
        changes = {}
        if enabled is not _REFIT_SETTING_UNSET:
            changes["enabled"] = bool(enabled)
        if intensity_percent is not _REFIT_SETTING_UNSET:
            changes["intensity_percent"] = float(intensity_percent)
        if mode is not _REFIT_SETTING_UNSET:
            changes["mode"] = str(mode or "surface")
        if clearance_percent is not _REFIT_SETTING_UNSET:
            changes["clearance_percent"] = float(clearance_percent)
        # Older callers use None to omit tightness; keep that compatibility.
        if tightness_percent is not None:
            changes["tightness_percent"] = float(tightness_percent)
            changes["tightness_initialized"] = True
        if not changes:
            raise ValueError("Change at least one Refit setting before applying.")
        session = self._session(session_id)
        with session.export_lock:
            self._required_morph_data(session)
            report = self._run_morph_query_locked(session, "morph_state")
            state = self._morph_state_from_report_locked(session, report, refresh_presets=False)
            bound = set(state.refit.garment_submesh_indices)
            missing = tuple(index for index in garment_indices if index not in bound)
            if missing:
                raise ValueError(f"Refit settings require bound garment parts: {', '.join(str(index) for index in missing)}")
            current = {item.submesh_index: item for item in state.refit.garment_settings}
            settings = tuple(replace(current[index], **changes) for index in garment_indices)
            report = self._run_morph_command_locked(
                session,
                "morph_configure_refit",
                _refit_settings_batch_payload(settings, include_masks=False),
                history_label="Configure Garment Refit",
                record_history=True,
            )
            return self._morph_result_and_state_locked(session, "morph_configure_refit", report)

    def configure_refit_islands(
        self, session_id: str, islands: Sequence[Mapping[str, object]], *,
        inherit: bool = False, **changes: object,
    ) -> tuple[MeshEditResult, MeshMorphState]:
        """Override whole selected islands, retaining every other Part and island."""
        fields = {"enabled", "intensity_percent", "mode", "clearance_percent", "tightness_percent"}
        if set(changes) - fields or (inherit and changes) or (not inherit and not changes):
            raise ValueError("Change fitting settings or restore Part settings for the selected islands.")
        if "tightness_percent" in changes:
            changes["tightness_initialized"] = True
        if not islands:
            raise ValueError("Select at least one whole mesh island.")
        from cdmw.modding.mesh_islands import mesh_islands
        from cdmw.services.mesh_service_morph_authoring import _strict_indices

        if type(inherit) is not bool:
            raise ValueError("Island inheritance must be boolean.")

        session = self._session(session_id)
        with session.export_lock:
            data = self._required_morph_data(session)
            report = self._run_morph_query_locked(session, "morph_state")
            state = self._morph_state_from_report_locked(session, report, refresh_presets=False)
            current = {item.submesh_index: item for item in state.refit.garment_settings}
            topology = data.topology_mesh or session.working_mesh
            edited: dict[int, MeshRefitGarmentSettings] = {}
            seen = set()
            for target in islands:
                if not isinstance(target, Mapping):
                    raise ValueError("Island fitting requires Part and face indices.")
                part = _strict_indices((target.get("submesh_index"),), label="Island Part")[0]
                faces = tuple(sorted(_strict_indices(target.get("face_indices"), label="Island faces")))
                key = (part, faces)
                if part not in current or not faces or key in seen:
                    raise ValueError("Island fitting requires distinct whole islands in bound garments.")
                if faces not in mesh_islands(topology.submeshes[part]):
                    raise ValueError("Select a whole mesh island before changing its fitting settings.")
                seen.add(key)
                parent = edited.get(part, current[part])
                overrides = {item.face_indices: item for item in parent.island_settings}
                if inherit:
                    overrides.pop(faces, None)
                else:
                    previous = overrides.get(faces) or MeshRefitIslandSettings(faces, **{
                        name: getattr(parent, name) for name in fields
                    }, tightness_initialized=parent.tightness_initialized)
                    overrides[faces] = replace(previous, **changes)
                edited[part] = replace(parent, island_settings=tuple(overrides.values()))
            report = self._run_morph_command_locked(
                session, "morph_configure_refit", _refit_settings_batch_payload(
                    tuple(edited.values()), include_masks=False, include_islands=True),
                history_label="Configure Island Refit", record_history=True,
            )
            return self._morph_result_and_state_locked(session, "morph_configure_refit", report)

    def fit_refit_to_body(
        self, session_id: str, *, reference_body: bool = True,
    ) -> tuple[MeshEditResult, MeshMorphState]:
        """Fit enabled garments in one transaction using the resident Part settings.

        With ``reference_body`` the fit also uses the body the garments were
        authored on, when the session's archive Refit assets name one (see
        :mod:`cdmw.services.mesh_refit_reference_lookup`). Otherwise it fits to
        the driver alone and, for archive assets, says why.
        """
        from cdmw.services.mesh_refit_reference_lookup import RefitReferenceLookup, find_refit_reference_body

        session = self._session(session_id)
        with session.export_lock:
            state = self._morph_state_from_report_locked(
                session, self._run_morph_query_locked(session, "morph_state"), refresh_presets=False)
            settings = _fit_to_body_settings(state)
            lookup = RefitReferenceLookup(None)
            if reference_body:
                lookup = find_refit_reference_body(
                    session.archive_refit_context, state.refit.garment_submesh_indices,
                    state.refit.driver_submesh_indices,
                )
            if lookup.reference is not None or (not reference_body and state.refit.reference_body is not None):
                return self._fit_reference_body_locked(session, settings, lookup.reference)
            report = self._run_morph_command_locked(
                session, "morph_configure_refit", _refit_settings_batch_payload(settings, include_masks=False),
                history_label="Fit to body", record_history=True,
            )
            if lookup.reason and session.archive_refit_context is not None and state.refit.reference_body is None:
                report = {**report, "diagnostics": [
                    *tuple(report.get("diagnostics") or ()), f"Fit to body used only the current body: {lookup.reason}.",
                ]}
            return self._morph_result_and_state_locked(session, "morph_configure_refit", report)

    def fit_refit_to_reference_body(
        self, session_id: str, reference: object,
    ) -> tuple[MeshEditResult, MeshMorphState]:
        """Fit enabled garments using the body they were authored on, as one undoable Fit.

        ``reference`` is a :class:`~cdmw.modding.mesh_refit_reference.RefitReferenceBody`
        (or its native payload): the authored body and the same vertices
        retargeted into the driver's bind pose. ``None`` fits to the driver
        alone. The Part settings get the same Fit defaults as
        :meth:`fit_refit_to_body`.
        """
        payload = reference.payload() if callable(getattr(reference, "payload", None)) else reference
        if payload is not None and not isinstance(payload, Mapping):
            raise ValueError("Fit to body requires a reference body.")
        session = self._session(session_id)
        with session.export_lock:
            state = self._morph_state_from_report_locked(
                session, self._run_morph_query_locked(session, "morph_state"), refresh_presets=False)
            return self._fit_reference_body_locked(session, _fit_to_body_settings(state), payload)

    def clear_refit_reference_body(self, session_id: str) -> tuple[MeshEditResult, MeshMorphState]:
        """Return the fit to the bound fitter, which uses only the driver body."""
        return self._simple_morph_command(
            session_id, "morph_set_reference_body", {"reference_body": None}, "Clear reference body", True,
        )

    def _fit_reference_body_locked(self, session, settings, reference) -> tuple[MeshEditResult, MeshMorphState]:
        payload = reference.payload() if callable(getattr(reference, "payload", None)) else reference
        request = dict(_refit_settings_batch_payload(settings, include_masks=False))
        request["reference_body"] = None if payload is None else dict(payload)
        report = self._run_morph_command_locked(
            session, "morph_set_reference_body", request, history_label="Fit to body", record_history=True,
        )
        return self._morph_result_and_state_locked(session, "morph_set_reference_body", report)

    def refit_diagnostics(
        self,
        session_id: str,
        garment_submesh_indices: Sequence[object],
        *,
        sample_limit: int = 2048,
        detail_limit: int = 24,
    ) -> dict[str, object]:
        """Measure the published fit without recomposing it or recording history."""
        if isinstance(garment_submesh_indices, (str, bytes)):
            raise ValueError("Refit diagnostics require explicit garment Part indices.")
        indices = tuple(garment_submesh_indices)
        if (
            not indices
            or len(indices) > 128
            or any(type(index) is not int or index < 0 for index in indices)
            or len(set(indices)) != len(indices)
        ):
            raise ValueError("Refit diagnostics require 1..128 unique garment Part indices.")
        if type(sample_limit) is not int or not len(indices) <= sample_limit <= 4096:
            raise ValueError("Refit diagnostics require 1..4096 samples and at least one per Part.")
        if type(detail_limit) is not int or not 1 <= detail_limit <= 64:
            raise ValueError("Refit diagnostics require 1..64 layer details.")
        indices = tuple(sorted(indices))
        session = self._session(session_id)
        with session.export_lock:
            self._ensure_native_morph_session_locked(session)
            # This is deliberately a query. The mutation path advances the
            # morph revision, captures undo state, and publishes geometry.
            report = native_mesh_editor_session_command(
                "morph_state",
                session.session_id,
                {
                    "include_refit_diagnostics": True,
                    "submesh_indices": indices,
                    "diagnostic_sample_limit": sample_limit,
                    "diagnostic_detail_limit": detail_limit,
                },
                timeout_seconds=10.0,
            )
            if not isinstance(report, Mapping) or str(report.get("status") or "").lower() != "ok":
                raise RuntimeError(_report_error(report, "Resident C++ Refit diagnostics failed."))
            raw = report.get("refit_diagnostics")
            if not isinstance(raw, Mapping) or raw.get("schema") != "cdmw.refit_diagnostics.v1":
                raise RuntimeError("Resident C++ Refit diagnostics returned an unsupported report.")
            diagnostics = dict(raw)
            diagnostics["shadow_revision"] = int(session.revision)
            diagnostics["requested_submesh_indices"] = list(indices)
            return diagnostics

    def clear_refit(self, session_id: str) -> tuple[MeshEditResult, MeshMorphState]:
        return self._simple_morph_command(session_id, "morph_clear_refit", {}, "Clear Garment Refit", True)

    def reset_morph(self, session_id: str) -> tuple[MeshEditResult, MeshMorphState]:
        if getattr(self._morph_sessions.get(session_id), "manual_values", None) is not None:
            return self._simple_layered_morph_command(session_id, "morph_reset", "Reset Morph")
        return self._simple_morph_command(session_id, "morph_reset", {}, "Reset Morph", True)

    def bake_morph(self, session_id: str) -> tuple[MeshEditResult, MeshMorphState]:
        if getattr(self._morph_sessions.get(session_id), "manual_values", None) is not None:
            return self._simple_layered_morph_command(session_id, "morph_bake", "Bake Morph")
        return self._simple_morph_command(session_id, "morph_bake", {}, "Bake Morph", True)

    def finish_morph(self, session_id: str) -> tuple[MeshEditResult, MeshMorphState]:
        if getattr(self._morph_sessions.get(session_id), "manual_values", None) is not None:
            return self._simple_layered_morph_command(session_id, "morph_finish", "Finish Morph")
        return self._simple_morph_command(session_id, "morph_finish", {}, "Finish Morph", True)

    def _simple_morph_command(
        self,
        session_id: str,
        command: str,
        payload: Mapping[str, object],
        history_label: str,
        record_history: bool,
    ) -> tuple[MeshEditResult, MeshMorphState]:
        session = self._session(session_id)
        with session.export_lock:
            report = self._run_morph_command_locked(session, command, payload, history_label=history_label, record_history=record_history)
            return self._morph_result_and_state_locked(session, command, report)

    def _profile_root(self):
        return mesh_morph_profile_root(self.settings)

    def _profile_driver_mesh_locked(self, session: _MeshEditSession) -> object:
        data = self._morph_sessions.get(session.session_id)
        if isinstance(data, _MeshMorphSessionData) and data.topology_mesh is not None:
            return data.topology_mesh
        return session.base_mesh

    def _profiles_locked(
        self,
        session: _MeshEditSession,
        *,
        refresh_topology: bool = False,
    ) -> tuple[tuple[MeshMorphProfile, ...], tuple[str, ...]]:
        data = self._morph_sessions.get(session.session_id)
        if not isinstance(data, _MeshMorphSessionData):
            data = _MeshMorphSessionData()
            self._morph_sessions[session.session_id] = data
        if data.topology_invalidated:
            if not refresh_topology:
                return (), tuple(dict.fromkeys((*data.diagnostics, "Topology changed; procedural profiles and refit bindings were invalidated.")))
            data.topology_mesh = self._working_mesh_locked(session, clone=False)
            data.topology_invalidated = False
            data.profiles_loaded = False
            data.available_profile_ids = ()
        if data.profiles_frozen and (refresh_topology or not data.profiles_loaded):
            mesh = self._profile_driver_mesh_locked(session)
            compatible: list[MeshMorphProfile] = []
            diagnostics: list[str] = []
            for profile in data.known_profiles.values():
                current = mesh_morph_driver_topology_fingerprint(
                    mesh,
                    profile.definitions,
                )
                if profile.topology_fingerprint == current:
                    compatible.append(profile)
                else:
                    diagnostics.append(
                        f"Procedural morph profile {profile.name} was omitted because its driver topology does not match."
                    )
            ordered = tuple(
                sorted(
                    compatible,
                    key=lambda item: (item.name.casefold(), item.profile_id),
                )
            )
            data.available_profile_ids = tuple(profile.profile_id for profile in ordered)
            data.profile_diagnostics = tuple(diagnostics)
            data.profiles_loaded = True
            return ordered, data.profile_diagnostics
        if data.profiles_loaded and not refresh_topology:
            cached = tuple(
                data.known_profiles[profile_id]
                for profile_id in data.available_profile_ids
                if profile_id in data.known_profiles
            )
            return tuple(sorted(cached, key=lambda item: (item.name.casefold(), item.profile_id))), data.profile_diagnostics
        mesh = self._profile_driver_mesh_locked(session)
        with mesh_morph_profile_lock(self._profile_root()):
            profiles, diagnostics = list_mesh_morph_profiles(
                self._profile_root(),
                mesh,
            )
        merged = {profile.profile_id: profile for profile in profiles}
        if data.profile is not None:
            merged[data.profile.profile_id] = data.profile
        ordered = tuple(sorted(merged.values(), key=lambda item: (item.name.casefold(), item.profile_id)))
        data.known_profiles.update(merged)
        data.available_profile_ids = tuple(profile.profile_id for profile in ordered)
        data.profile_diagnostics = tuple(diagnostics)
        data.profiles_loaded = True
        return ordered, diagnostics

    def _require_baked_morph_definition_edit(self, session: _MeshEditSession) -> None:
        self._require_no_pending_morph_authoring(session, include_baseline=True)
        data = self._morph_sessions.get(session.session_id)
        if isinstance(data, _MeshMorphSessionData) and data.state is not None and data.state.unbaked:
            raise RuntimeError("Bake or Reset active Morph & Refit values before editing profile definitions.")

    def _required_morph_data(self, session: _MeshEditSession) -> _MeshMorphSessionData:
        data = self._morph_sessions.get(session.session_id)
        if not isinstance(data, _MeshMorphSessionData) or data.profile is None:
            raise RuntimeError("Select a procedural morph profile first.")
        return data

    def _invalidate_morph_after_topology_locked(self, session: _MeshEditSession) -> None:
        data = self._morph_sessions.get(session.session_id)
        if not isinstance(data, _MeshMorphSessionData):
            # Ordinary Edit Mesh sessions must stay independent of Morph & Refit
            # persistence. A later first morph-state request will load profiles
            # against the then-current topology, so there is nothing to
            # invalidate until this session has actually used the feature.
            return
        if data.profile is not None:
            data.known_profiles[data.profile.profile_id] = data.profile
        data.profile = None
        data.preset_id = ""
        clear_morph_layers(data)
        data.corrections_enabled = True
        data.refit_setup_cache = None
        data.topology_mesh = None
        data.topology_invalidated = True
        data.profiles_loaded = False
        data.available_profile_ids = ()
        data.diagnostics = tuple(dict.fromkeys((*data.diagnostics, "Topology changed; procedural profiles and refit bindings were invalidated.")))
        try:
            data.topology_mesh = self._working_mesh_locked(session, clone=False)
            data.topology_invalidated = False
            report = self._run_morph_query_locked(session, "morph_state")
            self._remember_morph_state(
                session,
                self._morph_state_from_report_locked(session, report, refresh_profiles=False),
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            previous_revision = data.state.state_revision if data.state is not None else 0
            data.state = MeshMorphState(
                session_id=session.session_id,
                diagnostics=data.diagnostics,
                failure=f"Procedural profile compatibility refresh failed after topology changed: {exc}",
                state_revision=previous_revision + 1,
                edit_revision=session.revision,
                change_id="topology-invalidated",
            )

    def _refresh_cached_morph_after_history_locked(
        self,
        session: _MeshEditSession,
        *,
        topology_changed: bool,
    ) -> None:
        data = self._morph_sessions.get(session.session_id)
        if not isinstance(data, _MeshMorphSessionData):
            return
        if topology_changed:
            data.topology_mesh = self._working_mesh_locked(session, clone=False)
            data.topology_invalidated = False
            data.profiles_loaded = False
            data.available_profile_ids = ()
        report = self._run_morph_query_locked(session, "morph_state")
        self._remember_morph_state(
            session,
            self._morph_state_from_report_locked(session, report, refresh_profiles=False),
        )

    def _refresh_cached_morph_metadata_locked(self, session: _MeshEditSession) -> MeshMorphState:
        report = self._run_morph_query_locked(session, "morph_state")
        return self._remember_morph_state(
            session,
            self._morph_state_from_report_locked(session, report, refresh_profiles=False),
        )

    def _ensure_native_morph_session_locked(self, session: _MeshEditSession) -> None:
        if not native_mesh_core_available():
            raise RuntimeError("Procedural Morph & Refit requires the resident C++ mesh core.")
        _service_call("_refresh_native_editor_session_if_mesh_changed", session)
        if session.native_editor_session_ready:
            return
        if session.native_editor_mesh_dirty:
            raise RuntimeError("Resident C++ mesh state is dirty and cannot be reopened from stale Python geometry.")
        opened = open_native_mesh_editor_session(session.working_mesh, session.session_id, timeout_seconds=10.0)
        if opened is None:
            raise RuntimeError("Resident C++ Edit Mesh session failed to open.")
        session.native_editor_session_ready = True
        session.native_editor_selection_signature = ()
        session.native_editor_active_stroke_id = ""
        session.native_editor_mesh_signature = _service_call("_native_editor_mesh_storage_signature", session.working_mesh)  # type: ignore[assignment]

    def _run_morph_query_locked(self, session: _MeshEditSession, command: str) -> Mapping[str, object]:
        self._ensure_native_morph_session_locked(session)
        report = native_mesh_editor_session_command(command, session.session_id, timeout_seconds=5.0)
        if not isinstance(report, Mapping) or str(report.get("status") or "").lower() != "ok":
            raise RuntimeError(_report_error(report, f"Resident C++ {command} failed."))
        return report

    def _refit_output_exclusions_locked(self, session, garments):
        from cdmw.domain.mesh.replacement import bound_part_indices
        from cdmw.domain.mesh.topology import SubmeshTopologyProvenance, validate_topology_provenance

        state = session.replacement_state
        mesh = self._working_mesh_locked(session, clone=False)
        indices = bound_part_indices(mesh, state)
        targets = set(garments)
        rows = []
        for binding in state.parts:
            index = indices[binding.part_id]
            if index not in targets:
                continue
            if not binding.included:
                rows.append({"submesh_index": index, "all": True})
                continue
            excluded = set(binding.excluded_island_faces)
            if not excluded:
                continue
            part = mesh.submeshes[index]
            provenance = getattr(part, "topology_provenance", None)
            if isinstance(provenance, SubmeshTopologyProvenance):
                errors = validate_topology_provenance(provenance, output_vertex_count=len(part.vertices),
                                                     output_face_count=len(part.faces))
                if errors:
                    raise ValueError("Cannot fit excluded islands without valid source face identities.")
                origins = provenance.face_origins
            elif part.faces == session.base_mesh.submeshes[binding.target_index].faces:
                origins = range(len(part.faces))
            else:
                raise ValueError("Cannot fit excluded islands without valid source face identities.")
            faces = [face for face, origin in enumerate(origins) if origin in excluded]
            if faces:
                rows.append({"submesh_index": index, "face_indices": faces})
        return rows

    def _run_morph_command_locked(
        self,
        session: _MeshEditSession,
        command: str,
        payload: Mapping[str, object],
        *,
        history_label: str,
        record_history: bool,
    ) -> Mapping[str, object]:
        self._require_no_pending_morph_authoring(session, include_baseline=True)
        self._validate_authored_runtime_use_locked(session, command, payload)
        self._ensure_native_morph_session_locked(session)
        request = dict(payload)
        if command == "morph_bind" and session.replacement_state is not None:
            request["excluded_faces"] = self._refit_output_exclusions_locked(
                session, request.get("garment_submesh_indices", ()))
        request["delta_output_dir"] = _native_preview_delta_output_dir()
        request["include_edit_report"] = True
        started = time.perf_counter()
        # Layered outfits can take longer than 30 seconds to fit. Slider and
        # preset changes also recompose the fit, so share one bounded budget.
        report = native_mesh_editor_session_command(command, session.session_id, request, timeout_seconds=90.0)
        if not isinstance(report, Mapping) or str(report.get("status") or "").lower() != "ok":
            reason = last_native_mesh_core_job_error() if report is None else ""
            raise RuntimeError(_report_error(report, reason or f"Resident C++ {command} failed."))
        # From this point the resident runtime may already have changed. Move
        # the scalar CAS token before every fallible bookkeeping operation.
        session.morph_session_revision += 1
        accepted_report = dict(report)
        bookkeeping_deferred = False
        try:
            metrics = _native_editor_metrics(accepted_report)
        except Exception:
            metrics = {}
            bookkeeping_deferred = True
        metrics["native_morph_roundtrip_ms"] = max(0.0, (time.perf_counter() - started) * 1000.0)
        next_undo = list(session.undo_stack)
        next_redo = list(session.redo_stack)
        removed: list[_MeshHistorySnapshot] = []
        if command == "morph_change" and str(payload.get("phase") or "").strip().lower() == "cancel":
            change_id = str(payload.get("change_id") or "").strip()
            if (
                change_id
                and next_undo
                and next_undo[-1].native_editor_history
                and next_undo[-1].native_editor_stroke_id == change_id
            ):
                removed.append(next_undo.pop())
        history_published = bool(accepted_report.get("history_published")) and record_history
        if history_published:
            marker = _MeshHistorySnapshot(
                mesh=None,
                mode=session.mode,
                selection=session.selection,
                edit_operations=tuple(session.edit_operations),
                native_editor_history=True,
                native_editor_stroke_id=str(accepted_report.get("change_id") or ""),
                history_action=command,
                history_label=history_label,
                object_transform=session.object_transform,
            )
            try:
                _service_call("_capture_history_material_state", session, marker)
                marker.retained_bytes = int(
                    _service_call("_history_snapshot_retained_bytes", marker)
                )
            except Exception:
                marker.material_generation = None
                marker.committed_texture_resources = None
                marker.retained_bytes = 0
                bookkeeping_deferred = True
            removed.extend(next_redo)
            next_redo = []
            next_undo.append(marker)
        history_counts = (False, False)
        try:
            history_counts = _service_call("_update_native_history_usage", session, metrics)
        except Exception:
            bookkeeping_deferred = True
        try:
            max_count = max(1, int(self.max_history or 1))
            max_bytes = max(0, int(self.max_history_bytes or 0))
            while next_undo or next_redo:
                if len(next_undo) + len(next_redo) == 1:
                    break
                retained = int(
                    _service_call("_history_stack_retained_bytes", next_undo)
                ) + int(_service_call("_history_stack_retained_bytes", next_redo))
                if (
                    len(next_undo) + len(next_redo) <= max_count
                    and retained + session.native_history_retained_bytes <= max_bytes
                ):
                    break
                trim_stack = next_undo if next_undo else next_redo
                removed.append(trim_stack.pop(0))
        except Exception:
            bookkeeping_deferred = True
        session.undo_stack[:] = next_undo
        session.redo_stack[:] = next_redo
        try:
            _service_call("_trim_native_history_markers", session, *history_counts)
        except Exception:
            bookkeeping_deferred = True
        for discarded in removed:
            try:
                _service_call("_dispose_history_snapshot", discarded)
            except Exception:
                bookkeeping_deferred = True
        if bookkeeping_deferred:
            diagnostics = [
                str(item)
                for item in tuple(accepted_report.get("diagnostics") or ())
                if str(item).strip()
            ]
            diagnostics.append("Morph history cleanup was deferred after the edit was accepted.")
            accepted_report["diagnostics"] = diagnostics
            accepted_report["history_cleanup_deferred"] = True
        return accepted_report

    def _morph_result_and_state_locked(
        self,
        session: _MeshEditSession,
        action: str,
        report: Mapping[str, object],
    ) -> tuple[MeshEditResult, MeshMorphState]:
        previous_revision = session.revision
        counts = _native_editor_dirty_counts_from_report(report, current_submesh_count=len(session.working_mesh.submeshes))
        affected = _native_editor_report_affected_indices(report, len(counts) if counts else len(session.working_mesh.submeshes))
        changed = _native_editor_report_changed_vertices(report, counts or tuple((len(submesh.vertices), len(submesh.faces)) for submesh in session.working_mesh.submeshes))
        preview_vertices = native_mesh_editor_session_preview_vertex_update_groups(report)
        preview_triangles = native_mesh_editor_session_preview_triangle_groups(report)
        if affected or changed:
            if not counts:
                raise RuntimeError("Resident C++ morph report omitted submesh counts.")
            session.native_editor_mesh_dirty = True
            session.native_editor_mesh_dirty_counts = counts
            _apply_native_editor_dirty_counts(session)
            # A native fit/morph admits position and regenerated-normal edits,
            # just like a viewport transaction. Keep this ledger complete when
            # other channel edits already enabled exact-writer coverage checks.
            operations = list(session.edit_operations)
            recorded = {(row.operation, row.lod_index, row.submesh_index, row.vertex_count)
                        for row in mesh_edit_operations_from_dicts(operations)}
            for part in sorted(set(affected) | set(changed)):
                for operation in ("replace_positions_same_count", "replace_normals_same_count"):
                    key = (operation, session.lod_index, part, counts[part][0])
                    if key in recorded:
                        continue
                    operations.append({
                        "operation": operation, "lod_index": session.lod_index,
                        "submesh_index": part, "vertex_count": counts[part][0],
                        "source": "resident_native", "created_by": "CDMW Morph & Refit",
                        "metadata": {"service_action": action},
                    })
                    recorded.add(key)
            session.edit_operations = tuple(operations)
            session.revision += 1
            autosave = getattr(self, "_schedule_mesh_layer_autosave", None)
            if callable(autosave):
                autosave(session)
        elif bool(report.get("history_published")):
            session.revision += 1
            autosave = getattr(self, "_schedule_mesh_layer_autosave", None)
            if callable(autosave):
                autosave(session)
        metrics = _native_editor_metrics(report)
        result = self._result(
            session,
            action,
            affected=affected,
            changed=changed,
            native_preview_vertex_update_groups=preview_vertices,
            native_preview_triangle_groups=preview_triangles,
            submesh_counts=counts,
            diagnostics=tuple(str(item) for item in tuple(report.get("diagnostics") or ()) if str(item).strip()),
            metrics=metrics,
        )
        if action in {
            "morph_change", "morph_apply_preset", "morph_reset",
            "morph_set_macro", "morph_reset_macros", "morph_set_symmetry", "morph_set_side_value",
        }:
            self._carry_refit_setup_cache_locked(session, previous_revision)
        return result, self._remember_morph_state(session, self._morph_state_from_report_locked(session, report))

    def _remember_morph_state(self, session: _MeshEditSession, state: MeshMorphState) -> MeshMorphState:
        data = self._morph_sessions.get(session.session_id)
        if not isinstance(data, _MeshMorphSessionData):
            data = _MeshMorphSessionData()
            self._morph_sessions[session.session_id] = data
        if data.state is not None and state.state_revision <= data.state.state_revision:
            state = replace(state, state_revision=data.state.state_revision + 1)
        data.state = state
        return state

    def _morph_state_from_report_locked(
        self,
        session: _MeshEditSession,
        report: Mapping[str, object],
        *,
        refresh_profiles: bool = False,
        refresh_presets: bool = True,
    ) -> MeshMorphState:
        data = self._morph_sessions.get(session.session_id)
        profiles, profile_diagnostics = self._profiles_locked(
            session,
            refresh_topology=refresh_profiles,
        )
        native_state = report.get("morph_state")
        raw_state = native_state if isinstance(native_state, Mapping) else report
        active_profile_id = str(raw_state.get("profile_id") or "")
        if not isinstance(data, _MeshMorphSessionData):
            data = _MeshMorphSessionData()
            self._morph_sessions[session.session_id] = data
        profile = data.known_profiles.get(active_profile_id) if active_profile_id else None
        if profile is None and active_profile_id:
            profile = next((item for item in profiles if item.profile_id == active_profile_id), None)
        data.profile = profile
        if profile is not None:
            data.known_profiles[profile.profile_id] = profile
        if profile is not None and refresh_presets and not data.profiles_frozen and self.settings is not None:
            with mesh_morph_profile_lock(self._profile_root()):
                presets, preset_diagnostics = list_mesh_morph_presets(
                    self._profile_root(),
                    profile,
                )
            for preset in presets:
                data.known_presets[(profile.profile_id, preset.preset_id)] = preset
        elif profile is not None:
            presets = tuple(
                preset
                for (profile_id, _preset_id), preset in data.known_presets.items()
                if profile_id == profile.profile_id
            )
            presets = tuple(
                sorted(presets, key=lambda item: (item.name.casefold(), item.preset_id))
            )
            preset_diagnostics = ()
        else:
            presets, preset_diagnostics = (), ()
        raw_preset_id = str(raw_state.get("preset_id") or "")
        available_preset_ids = {preset.preset_id for preset in presets}
        data.preset_id = raw_preset_id if raw_preset_id in available_preset_ids else ""
        raw_refit = raw_state.get("refit")
        refit = raw_refit if isinstance(raw_refit, Mapping) else {}
        vertex_masks = _refit_masks_from_report(refit)
        garment_regions = tuple(
            (
                int(item.get("garment_submesh_index", -1)),
                tuple(
                    MeshRefitDriverRegion(
                        submesh_index=region.get("submesh_index"),
                        vertex_indices=tuple(region.get("vertex_indices") or ()),
                    )
                    for region in tuple(item.get("driver_regions") or ())
                    if isinstance(region, Mapping)
                ),
            )
            for item in tuple(refit.get("garment_regions") or ())
            if isinstance(item, Mapping)
        )
        garment_settings = tuple(
            MeshRefitGarmentSettings(
                submesh_index=int(item.get("submesh_index", -1)),
                enabled=bool(item.get("enabled", True)),
                intensity_percent=float(item.get("intensity_percent", 100.0)),
                mode=str(item.get("mode") or "surface"),
                clearance_percent=float(item.get("clearance_percent", 0.0)),
                tightness_percent=float(item.get("tightness_percent", 0.0)),
                tightness_initialized=item.get("tightness_initialized", True),
                vertex_mask=vertex_masks.get(int(item.get("submesh_index", -1))),
                island_settings=tuple(MeshRefitIslandSettings(
                    face_indices=tuple(island["face_indices"]),
                    **{key: island[key] for key in ("enabled", "intensity_percent", "mode", "clearance_percent", "tightness_percent")},
                    tightness_initialized=island.get("tightness_initialized", True),
                ) for island in item.get("island_settings", ())),
            )
            for item in tuple(refit.get("garment_settings") or ())
            if isinstance(item, Mapping)
        )
        diagnostics = tuple(dict.fromkeys(
            str(item)
            for item in (
                *data.diagnostics,
                *profile_diagnostics,
                *preset_diagnostics,
                *(tuple(raw_state.get("diagnostics") or ())),
            )
            if str(item).strip()
        ))
        body_available, body_reason = self._body_controls_availability_locked(session, raw_state)
        layer_fields = self._morph_layer_state_fields_locked(
            session, data, profile, _morph_values_from_report(raw_state),
        )
        return MeshMorphState(
            session_id=session.session_id,
            body_controls_available=body_available,
            body_controls_reason=body_reason,
            **layer_fields,
            profile_id=active_profile_id,
            preset_id=data.preset_id,
            topology_fingerprint=(profile.topology_fingerprint if profile is not None else ""),
            definitions=(profile.definitions if profile is not None else ()),
            values=tuple(sorted(_morph_values_from_report(raw_state).items())),
            available_profiles=tuple((item.profile_id, item.name) for item in profiles),
            available_presets=tuple((item.preset_id, item.name) for item in presets),
            driver_submesh_indices=_indices(raw_state.get("driver_submesh_indices") or ()),
            refit=MeshRefitBindingSummary(
                driver_submesh_indices=_indices(refit.get("driver_submesh_indices") or ()),
                garment_submesh_indices=_indices(refit.get("garment_submesh_indices") or ()),
                bound_vertex_count=int(refit.get("bound_vertex_count", 0) or 0),
                maximum_distance=float(refit.get("maximum_distance", 0.0) or 0.0),
                p95_distance=float(refit.get("p95_distance", 0.0) or 0.0),
                warning_distance=float(refit.get("warning_distance", 0.0) or 0.0),
                distance_warning=bool(refit.get("distance_warning")),
                driver_triangle_count=int(refit.get("driver_triangle_count", 0) or 0),
                candidate_triangle_tests=int(refit.get("candidate_triangle_tests", 0) or 0),
                garment_settings=tuple(sorted(garment_settings, key=lambda item: item.submesh_index)),
                garment_regions=tuple(sorted(garment_regions)),
                reference_body=_refit_reference_body_from_report(refit.get("reference_body")),
            ),
            unbaked=bool(raw_state.get("unbaked")),
            topology_blocked=bool(raw_state.get("topology_blocked")),
            busy=bool(raw_state.get("busy")),
            failure=str(raw_state.get("failure") or ""),
            diagnostics=diagnostics,
            state_revision=int(raw_state.get("state_revision", 0) or 0),
            edit_revision=int(raw_state.get("edit_revision", session.revision) or 0),
            change_id=str(raw_state.get("change_id") or ""),
            authoring_baseline_ready=data.authoring_baseline is not None,
            authoring_driver_submesh_indices=(data.authoring_baseline.driver_submesh_indices if data.authoring_baseline is not None else ()),
            correction_definition_id=(data.correction_capture.definition_id if data.correction_capture is not None else ""),
            correction_garment_submesh_indices=(data.correction_capture.garment_submesh_indices if data.correction_capture is not None else ()),
            corrections_enabled=data.corrections_enabled,
            **self._refit_shape_restore_state_fields_locked(session),
            **self._matching_refit_setup_state_fields_locked(session, data, raw_state),
        )


def _fit_to_body_settings(state: MeshMorphState) -> tuple[MeshRefitGarmentSettings, ...]:
    """Enabled Part settings with Fit's defaults: fresh setups fit at 100% Tightness, 0.1% Clearance at least."""
    def fit_settings(item):
        if not item.enabled:
            return item
        return replace(item,
            tightness_percent=item.tightness_percent if item.tightness_initialized or item.mode == "rigid" else 100.,
            tightness_initialized=True,
            clearance_percent=max(0.1, item.clearance_percent))
    settings = tuple(
        replace(fit_settings(item), island_settings=tuple(fit_settings(island) for island in item.island_settings))
        for item in state.refit.garment_settings if item.enabled or any(island.enabled for island in item.island_settings)
    )
    if not settings:
        raise ValueError("Enable and bind a garment before fitting it to the body.")
    return settings


def _refit_reference_body_from_report(raw: object) -> MeshRefitReferenceBodySummary | None:
    if not isinstance(raw, Mapping):
        return None
    last_fit = raw.get("last_fit")
    return MeshRefitReferenceBodySummary(
        label=str(raw.get("label") or ""),
        vertex_count=int(raw.get("vertex_count", 0) or 0),
        face_count=int(raw.get("face_count", 0) or 0),
        last_fit=tuple(sorted(
            (str(key), value) for key, value in last_fit.items()
            if isinstance(value, (str, int, float, bool))
        )) if isinstance(last_fit, Mapping) else (),
    )


def _indices(values: object) -> tuple[int, ...]:
    result: set[int] = set()
    for value in tuple(values or ()):  # type: ignore[arg-type]
        try:
            index = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if index >= 0:
            result.add(index)
    return tuple(sorted(result))


def _morph_values_from_report(report: Mapping[str, object]) -> dict[str, float]:
    raw_values = report.get("values")
    if not isinstance(raw_values, Mapping):
        raw_state = report.get("morph_state")
        raw_values = raw_state.get("values") if isinstance(raw_state, Mapping) else None
    values: dict[str, float] = {}
    if isinstance(raw_values, Mapping):
        for raw_key, raw_value in raw_values.items():
            try:
                values[str(raw_key)] = float(raw_value)
            except (TypeError, ValueError, OverflowError):
                continue
    return values


def _report_error(report: object, fallback: str) -> str:
    if isinstance(report, Mapping):
        for key in ("error", "failure", "message"):
            value = str(report.get(key) or "").strip()
            if value:
                return value
    return fallback


__all__ = [
    "MeshMorphServiceMixin",
    "defer_mesh_morph_session_state_disposal",
    "dispose_mesh_morph_session_state",
    "mesh_morph_profile_lock",
    "retry_deferred_mesh_morph_session_state_disposals",
]
