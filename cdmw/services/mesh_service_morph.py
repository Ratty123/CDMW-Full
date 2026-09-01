"""Resident procedural morph/refit authority for :class:`MeshService`."""
from __future__ import annotations

import copy
import json
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
    MeshMorphDefinition,
    MeshMorphProfile,
    MeshMorphRule,
    MeshMorphState,
    MeshMorphValuePreset,
    MeshRefitBindingSummary,
    MeshRefitGarmentSettings,
    build_weighted_morph_selection,
    clamp_morph_value,
    generate_procedural_morph_fields,
    mesh_morph_driver_topology_fingerprint,
    procedural_morph_pivot,
)
from cdmw.modding.mesh_native_core import (
    _native_preview_delta_output_dir,
    create_native_mesh_editor_morph_runtime_snapshot,
    dispose_native_mesh_editor_morph_runtime_snapshot,
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
    save_mesh_morph_preset,
    save_mesh_morph_profile,
    serialized_mesh_morph_preset,
    serialized_mesh_morph_profile,
)
from cdmw.services.mesh_service_history import (
    _MESH_MORPH_PROFILE_MAX_FILE_BYTES,
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
from cdmw.services.mesh_service_state import (
    _MeshEditSession,
    _MeshHistorySnapshot,
    _MeshMorphSessionState,
)


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


_DEFERRED_MORPH_DISPOSAL_LOCK = threading.Lock()
_DEFERRED_MORPH_DISPOSALS: list[_MeshMorphSessionState] = []
_MORPH_PROFILE_LOCKS_GUARD = threading.Lock()
_MORPH_PROFILE_LOCKS: dict[str, threading.RLock] = {}
_MORPH_MAX_DEFINITIONS = 512
_MORPH_NATIVE_MESSAGE_MAX_BYTES = 64 * 1024 * 1024


def _require_bounded_morph_json(value: object, *, limit: int, label: str) -> None:
    encoded_bytes = 0
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"))
    for chunk in encoder.iterencode(value):
        encoded_bytes += len(chunk.encode("utf-8"))
        if encoded_bytes > int(limit):
            raise RuntimeError(f"{label} exceeds its {int(limit) // (1024 * 1024)} MiB limit")


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


class MeshMorphServiceMixin:
    """Keep UI shells thin while the resident C++ session owns deformation."""

    def capture_morph_session_state(self, session_id: str) -> _MeshMorphSessionState:
        """Capture an owned exact runtime snapshot without changing its source."""

        session = self._session(session_id)
        with session.export_lock:
            return self._capture_morph_session_state_locked(session)

    def _capture_morph_session_state_locked(
        self,
        session: _MeshEditSession,
    ) -> _MeshMorphSessionState:
        data = self._morph_sessions.get(session.session_id)
        if not isinstance(data, _MeshMorphSessionData):
            return _MeshMorphSessionState(
                present=False,
                session_revision=max(0, int(session.morph_session_revision)),
            )

        self._ensure_native_morph_session_locked(session)
        native_snapshot = create_native_mesh_editor_morph_runtime_snapshot(
            session.session_id,
            timeout_seconds=15.0,
        )
        if native_snapshot is None:
            raise RuntimeError("Resident C++ Morph & Refit runtime snapshot capture failed.")
        try:
            cache = self._clone_morph_session_data(
                data,
                operation="morph.runtime_state_capture",
            )
            retained_bytes = int(native_snapshot.get("retained_bytes") or 0)
            if retained_bytes <= 0:
                raise RuntimeError("Resident C++ Morph & Refit runtime snapshot omitted retained bytes.")
            return _MeshMorphSessionState(
                present=True,
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

        if not state.present:
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
        if not isinstance(state.cache, _MeshMorphSessionData):
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
        )
        cache.profiles_loaded = self.settings is None or not reconcile_profiles
        cache.available_profile_ids = (
            tuple(sorted(cache.known_profiles))
            if self.settings is None or not reconcile_profiles
            else ()
        )
        previous_cache = self._morph_sessions.get(session.session_id)
        native_ready_before = session.native_editor_session_ready
        self._morph_sessions[session.session_id] = cache
        try:
            # Reconcile persisted profiles before resident runtime changes, but
            # keep the captured unsaved profile in the merged cache.
            if self.settings is not None and reconcile_profiles:
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
                raise RuntimeError("Resident C++ Morph & Refit runtime snapshot restore failed.")
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
        session.native_history_undo_count = 0
        session.native_history_redo_count = 0
        session.native_history_retained_bytes = 0
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
    ) -> _MeshHistorySnapshot:
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
                session
            )
        except Exception:
            _service_call("_dispose_history_snapshot", snapshot)
            raise
        snapshot.history_action = str(action)
        snapshot.history_label = str(label)
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
        if snapshot.morph_profile_root is None:
            raise RuntimeError("Morph profile history has no settings-owned root.")
        if session.native_editor_mesh_dirty and not _service_call(
            "_sync_native_editor_session_to_working_mesh",
            session,
        ):
            raise RuntimeError(
                "Resident C++ mesh export failed before Morph profile history publication."
            )
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

    @staticmethod
    def _preflight_morph_profile_history_file_locked(
        snapshot: _MeshHistorySnapshot,
        relative: str,
        document: str,
    ) -> None:
        candidate = {
            str(path): bytes(data)
            for path, data in tuple(snapshot.morph_profile_files or ())
        }
        candidate[str(relative)] = str(document).encode("utf-8")
        _validated_mesh_morph_profile_files(
            tuple(sorted(candidate.items(), key=lambda item: item[0].casefold()))
        )

    def _rollback_unpublished_morph_profile_history_locked(
        self,
        session: _MeshEditSession,
        snapshot: _MeshHistorySnapshot,
    ) -> None:
        """Restore a profile transaction that failed before history publication."""

        outcome = None
        try:
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
            profile=copy.deepcopy(data.profile),
            preset_id=str(data.preset_id),
            diagnostics=tuple(str(item) for item in data.diagnostics),
            state=copy.deepcopy(data.state),
            known_profiles=copy.deepcopy(data.known_profiles),
            known_presets=copy.deepcopy(data.known_presets),
            available_profile_ids=tuple(str(item) for item in data.available_profile_ids),
            profile_diagnostics=tuple(str(item) for item in data.profile_diagnostics),
            profiles_loaded=bool(data.profiles_loaded),
            profiles_frozen=bool(data.profiles_frozen),
            topology_mesh=topology_mesh,
            topology_invalidated=bool(data.topology_invalidated),
        )

    def _apply_morph_edit_command_locked(
        self,
        session: _MeshEditSession,
        command: MeshEditCommand,
    ) -> MeshEditResult:
        action = str(command.action or "").strip().lower()
        params = dict(command.params or {})
        selection = command.selection if command.selection is not None else session.selection
        if action == "morph_refresh":
            self.morph_state(session.session_id)
            return self._result(session, action)
        if action == "morph_activate":
            return self.activate_morph_profile(session.session_id, params.get("profile_id"))[0]
        if action == "morph_author_definition":
            if command.selection is not None:
                session.selection = command.selection
            profile = self.create_morph_definition(
                session.session_id,
                **{key: value for key, value in params.items() if key != "stop_event"},
            )
            data = self._required_morph_data(session)
            return self._activate_morph_profile_locked(session, profile, data.diagnostics)[0]
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
                enabled=params.get("enabled", True),
                intensity_percent=params.get("intensity_percent", 100.0),
                mode=params.get("mode", "surface"),
                clearance_percent=params.get("clearance_percent", 0.0),
            )[0]
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
    ) -> tuple[MeshEditResult, MeshMorphState]:
        if len(profile.definitions) > _MORPH_MAX_DEFINITIONS:
            raise RuntimeError(
                f"Morph profiles support at most {_MORPH_MAX_DEFINITIONS} definitions"
            )
        serialized_mesh_morph_profile(
            profile,
            max_bytes=_MESH_MORPH_PROFILE_MAX_FILE_BYTES,
        )
        driver_mesh = self._profile_driver_mesh_locked(session)
        current_fingerprint = mesh_morph_driver_topology_fingerprint(driver_mesh, profile.definitions)
        if profile.topology_fingerprint != current_fingerprint:
            raise RuntimeError("Procedural morph profile topology does not match the active Edit Mesh driver.")
        fields = [
            sparse
            for definition in profile.definitions
            for sparse in generate_procedural_morph_fields(driver_mesh, definition)
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
                        "vertex_indices": list(sparse.vertex_indices),
                        "deltas": [list(delta) for delta in sparse.deltas],
                    }
                    for sparse in fields
                ],
            }
        }
        _require_bounded_morph_json(
            upload_payload,
            limit=_MORPH_NATIVE_MESSAGE_MAX_BYTES,
            label="Resident Morph upload",
        )
        report = self._run_morph_command_locked(
            session,
            "morph_upload",
            upload_payload,
            history_label="Select Morph Profile",
            record_history=True,
        )
        data = self._morph_sessions.get(session.session_id)
        if not isinstance(data, _MeshMorphSessionData):
            data = _MeshMorphSessionData()
            self._morph_sessions[session.session_id] = data
        data.profile = profile
        data.preset_id = ""
        data.diagnostics = tuple(diagnostics)
        data.known_profiles[profile.profile_id] = profile
        data.available_profile_ids = tuple(dict.fromkeys((*data.available_profile_ids, profile.profile_id)))
        data.topology_invalidated = False
        return self._morph_result_and_state_locked(session, "morph_upload", report)

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
            if len(profile.definitions) > _MORPH_MAX_DEFINITIONS:
                raise RuntimeError(
                    f"Morph profiles support at most {_MORPH_MAX_DEFINITIONS} definitions"
                )
            serialized_mesh_morph_profile(
                profile,
                max_bytes=_MESH_MORPH_PROFILE_MAX_FILE_BYTES,
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
                relative, document = serialized_mesh_morph_profile(
                    profile,
                    max_bytes=_MESH_MORPH_PROFILE_MAX_FILE_BYTES,
                )
                self._preflight_morph_profile_history_file_locked(
                    history,
                    relative,
                    document,
                )
            except Exception:
                _service_call("_dispose_history_snapshot", history)
                raise
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
            )
            try:
                relative, document = serialized_mesh_morph_preset(
                    preset,
                    max_bytes=_MESH_MORPH_PROFILE_MAX_FILE_BYTES,
                )
                self._preflight_morph_profile_history_file_locked(
                    history,
                    relative,
                    document,
                )
            except Exception:
                _service_call("_dispose_history_snapshot", history)
                raise
            try:
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
        enabled: object,
        intensity_percent: object,
        mode: object,
        clearance_percent: object,
    ) -> tuple[MeshEditResult, MeshMorphState]:
        garment_indices = _indices(garment_submesh_indices)
        if not garment_indices:
            raise ValueError("Refit settings require at least one bound garment part.")
        settings = MeshRefitGarmentSettings(
            submesh_index=garment_indices[0],
            enabled=bool(enabled),
            intensity_percent=float(intensity_percent),
            mode=str(mode or "surface"),
            clearance_percent=float(clearance_percent),
        )
        session = self._session(session_id)
        with session.export_lock:
            data = self._required_morph_data(session)
            bound = set(data.state.refit.garment_submesh_indices if data.state is not None else ())
            missing = tuple(index for index in garment_indices if index not in bound)
            if missing:
                raise ValueError(f"Refit settings require bound garment parts: {', '.join(str(index) for index in missing)}")
            report = self._run_morph_command_locked(
                session,
                "morph_configure_refit",
                {
                    "garment_submesh_indices": garment_indices,
                    "enabled": settings.enabled,
                    "intensity_percent": settings.intensity_percent,
                    "mode": settings.mode,
                    "clearance_percent": settings.clearance_percent,
                },
                history_label="Configure Garment Refit",
                record_history=True,
            )
            return self._morph_result_and_state_locked(session, "morph_configure_refit", report)

    def clear_refit(self, session_id: str) -> tuple[MeshEditResult, MeshMorphState]:
        return self._simple_morph_command(session_id, "morph_clear_refit", {}, "Clear Garment Refit", True)

    def reset_morph(self, session_id: str) -> tuple[MeshEditResult, MeshMorphState]:
        return self._simple_morph_command(session_id, "morph_reset", {}, "Reset Morph", True)

    def bake_morph(self, session_id: str) -> tuple[MeshEditResult, MeshMorphState]:
        return self._simple_morph_command(session_id, "morph_bake", {}, "Bake Morph", True)

    def finish_morph(self, session_id: str) -> tuple[MeshEditResult, MeshMorphState]:
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

    def _run_morph_command_locked(
        self,
        session: _MeshEditSession,
        command: str,
        payload: Mapping[str, object],
        *,
        history_label: str,
        record_history: bool,
    ) -> Mapping[str, object]:
        self._ensure_native_morph_session_locked(session)
        request = dict(payload)
        request["delta_output_dir"] = _native_preview_delta_output_dir()
        request["include_edit_report"] = True
        started = time.perf_counter()
        report = native_mesh_editor_session_command(command, session.session_id, request, timeout_seconds=30.0)
        if not isinstance(report, Mapping) or str(report.get("status") or "").lower() != "ok":
            raise RuntimeError(_report_error(report, f"Resident C++ {command} failed."))
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
        try:
            _service_call("_update_native_history_usage", session, metrics)
        except Exception:
            bookkeeping_deferred = True
        try:
            max_count = max(1, int(self.max_history or 1))
            max_bytes = max(0, int(self.max_history_bytes or 0))
            while next_undo or next_redo:
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
            session.revision += 1
            autosave = getattr(self, "_schedule_mesh_layer_autosave", None)
            if callable(autosave):
                autosave(session)
        elif bool(report.get("history_published")):
            session.revision += 1
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
        if profile is not None and refresh_presets and not data.profiles_frozen:
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
        garment_settings = tuple(
            MeshRefitGarmentSettings(
                submesh_index=int(item.get("submesh_index", -1)),
                enabled=bool(item.get("enabled", True)),
                intensity_percent=float(item.get("intensity_percent", 100.0)),
                mode=str(item.get("mode") or "surface"),
                clearance_percent=float(item.get("clearance_percent", 0.0)),
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
        return MeshMorphState(
            session_id=session.session_id,
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
            ),
            unbaked=bool(raw_state.get("unbaked")),
            topology_blocked=bool(raw_state.get("topology_blocked")),
            busy=bool(raw_state.get("busy")),
            failure=str(raw_state.get("failure") or ""),
            diagnostics=diagnostics,
            state_revision=int(raw_state.get("state_revision", 0) or 0),
            edit_revision=int(raw_state.get("edit_revision", session.revision) or 0),
            change_id=str(raw_state.get("change_id") or ""),
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
