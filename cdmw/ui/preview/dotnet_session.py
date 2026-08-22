"""Resident, retrying QProcess controller for the shared .NET/Vortice preview."""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from cdmw.services.atomic_file_service import atomic_copy_file
from cdmw.services.preview_rendering_service import (
    acquire_dotnet_preview_package_cache_lease_for_path,
)
from cdmw.services.mesh_dotnet_experiment import (
    MeshDotNetExperimentPackage,
    mesh_dotnet_experiment_command,
    mesh_dotnet_experiment_package_from_path,
    mesh_dotnet_helper_provenance_blockers,
    mesh_dotnet_helper_static_provenance_blockers,
    mesh_dotnet_renderer_blockers,
    resolve_mesh_dotnet_experiment_editor,
)
from cdmw.ui.mesh_editor.process_io import (
    DOTNET_PROTOCOL_BUFFER_LIMIT,
    DOTNET_PROTOCOL_LINE_LIMIT,
    append_bounded_text,
    qprocess_is_running,
    stop_qprocess_async,
)
from cdmw.ui.preview.profile import DotNetPreviewProfile
from cdmw.ui.preview.dotnet_session_localization import DotNetPreviewSessionLocalizationMixin


_TRANSIENT_RETRY_DELAYS_MS = (500, 1_000, 2_000, 5_000)
_STEADY_RETRY_DELAY_MS = 5_000
_STATIC_RETRY_DELAY_MS = 30_000
_READY_TIMEOUT_MS = 10_000
_PACKAGE_TIMEOUT_MS = 15_000
_MATERIAL_SYNC_TIMEOUT_MS = 120_000

_BASE_PROTOCOL_CAPABILITIES = (
    "helper_build_provenance_v1",
    "resident_package_load_v1",
    "resident_preview_package_replace_v2",
    "deterministic_offscreen_capture_v1",
    "absolute_camera_state_v1",
    "view_state_changed_v1",
    "overlay_state_update_v1",
    "skeleton_overlay_v1",
    "pbd_cloth_overlay_v1",
    "ui_localization_v1",
)
_PREVIEW_PROTOCOL_CAPABILITIES = (
    "preview_profile_read_only_v1",
    "preview_session_v1",
    "read_only_part_pick_v1",
)
_AUTHORING_PROTOCOL_CAPABILITIES = (
    "mesh_edit_revision_ack_v1",
    "resident_mutation_envelope_v2",
    "host_tool_state_v1",
    "correlated_selection_strokes_v1",
    "geometry_layers_v1",
)


class DotNetPreviewSessionController(DotNetPreviewSessionLocalizationMixin, QObject):
    """Own exactly one helper process and a latest-wins resident package stream."""

    state_changed = Signal(str, str)
    protocol_event = Signal(object)
    renderer_ready = Signal(object)
    package_applied = Signal(str, int)
    package_failed = Signal(str, int, str)
    view_state_changed = Signal(object)
    part_pick_result = Signal(object)
    capture_completed = Signal(object)
    rehydrate_requested = Signal(int)
    localization_applied = Signal(str, int)

    def __init__(
        self,
        *,
        host_hwnd: Callable[[], int],
        profile: DotNetPreviewProfile | str = DotNetPreviewProfile.PREVIEW,
        configured_executable: Path | str | None = None,
        terminate_on_close: bool = False,
        authoring_rehydrator: Callable[["DotNetPreviewSessionController"], bool] | None = None,
        process_factory: Callable[[QObject], object] | None = None,
        direct_authoring: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.profile = DotNetPreviewProfile.normalize(profile)
        self._host_hwnd = host_hwnd
        self._configured_executable = configured_executable
        self._terminate_on_close = bool(terminate_on_close)
        self._authoring_rehydrator = authoring_rehydrator
        self._process_factory = process_factory or (lambda owner: QProcess(owner))
        self._direct_authoring = bool(direct_authoring)

        self._process: object | None = None
        self._process_generation = 0
        self._package_generation = 0
        self._package_request_id = 0
        self._pending_package_generation = 0
        self._protocol_request_id = 0
        self._launch_package_generation = 0
        self._launch_package_path = ""
        self._launch_is_prewarm = False
        self._prewarm_package: MeshDotNetExperimentPackage | None = None
        self._desired_package: MeshDotNetExperimentPackage | None = None
        self._desired_package_identity: tuple[str, str, str] | None = None
        self._applied_package: MeshDotNetExperimentPackage | None = None
        self._applied_package_identity: tuple[str, str, str] | None = None
        self._invalid_retry_package_path = ""
        self._invalid_retry_status_path = ""
        self._invalid_retry_reset_view = False
        self._applied_package_path = ""
        self._applied_package_generation = 0
        self._resident_material_signature = ""
        self._visible = True
        self._closed = False
        self._protocol_ready = False
        self._renderer_ready = False
        self._session_established = False
        self._session_provisional = False
        self._session_released = False
        self._active = False
        self._activation_request_id = 0
        self._pending_activation: dict[str, int | str] | None = None
        self._activation_waiting_for_material_sync = False
        self._activation_material_sync_generation = 0
        self._activation_retry_count = 0
        self._retry_attempt = 0
        self._retry_reason = ""
        self._executable = Path()
        self._stdout_buffer = b""
        self._stdout_tail = ""
        self._stderr_tail = ""
        self._capabilities: set[str] = set()
        self._session_id = uuid.uuid4().hex
        self._resident_state: OrderedDict[str, tuple[str, dict[str, object]]] = OrderedDict()
        self._authoring_scene_modes: dict[str, str] = {}
        self._package_leases: dict[str, object] = {}
        self._pending_captures: dict[int, tuple[Path, Path]] = {}
        self._prewarm_capture_request_id = 0
        self._prewarm_capture_path: Path | None = None
        self._last_event: dict[str, object] = {}
        self._ui_localizer: object | None = None
        self._localization_keys: tuple[str, ...] = ()
        self._localization_key_manifest_hash = ""
        self._localization_request_id = 0
        self._pending_localization: dict[str, object] | None = None
        self._localization_initial_established = True
        self._localization_applied_revision = -1
        self._renderer_ready_payload: dict[str, object] | None = None
        self._renderer_ready_announced = False

        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._launch_if_needed)
        self._ready_timer = QTimer(self)
        self._ready_timer.setSingleShot(True)
        self._ready_timer.timeout.connect(self._handle_ready_timeout)
        self._package_timer = QTimer(self)
        self._package_timer.setSingleShot(True)
        self._package_timer.timeout.connect(self._handle_package_timeout)
        self._activation_timer = QTimer(self)
        self._activation_timer.setSingleShot(True)
        self._activation_timer.timeout.connect(self._handle_activation_timeout)

    @property
    def process_generation(self) -> int:
        return self._process_generation

    @property
    def package_generation(self) -> int:
        return self._package_generation

    @property
    def applied_package_generation(self) -> int:
        return self._applied_package_generation

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(self._capabilities)

    @property
    def process(self) -> object | None:
        return self._process

    @property
    def process_id(self) -> int:
        process = self._process
        if process is None:
            return 0
        try:
            return max(0, int(process.processId()))
        except (AttributeError, RuntimeError, TypeError, ValueError, OverflowError):
            return 0

    @property
    def is_running(self) -> bool:
        return self._process is not None and qprocess_is_running(self._process)

    def set_configured_executable(self, executable: Path | str | None) -> None:
        self._configured_executable = executable

    def set_ui_localizer(self, localizer: object | None) -> None:
        if localizer is self._ui_localizer:
            return
        previous_signal = getattr(
            self._ui_localizer,
            "language_changed",
            None,
        )
        if previous_signal is not None:
            try:
                previous_signal.disconnect(self._handle_ui_language_changed)
            except (RuntimeError, TypeError):
                pass
        self._ui_localizer = localizer
        signal = getattr(localizer, "language_changed", None)
        if signal is not None:
            try:
                signal.connect(self._handle_ui_language_changed)
            except (RuntimeError, TypeError):
                pass
        if self._protocol_ready and self._localization_keys:
            self._send_ui_localization_state()

    def _handle_ui_language_changed(
        self,
        _language_code: str,
        _revision: int,
    ) -> None:
        if self._protocol_ready and self._localization_keys:
            self._send_ui_localization_state()

    def _reset_localization_handshake(self) -> None:
        self._localization_keys = ()
        self._localization_key_manifest_hash = ""
        self._pending_localization = None
        self._localization_initial_established = False
        self._localization_applied_revision = -1
        self._renderer_ready_payload = None
        self._renderer_ready_announced = False

    def _follow_preview_package_session(self, resolved: object, scene_session_id: str) -> bool:
        """Adopt the session id a read-only preview package declares.

        Loading a simple-preview package makes the renderer latch that package's
        scene session id as its resident session, and every correlated message is
        then compared against it by ordinal equality. A preview host that kept the
        random id it generated at construction therefore had *every*
        ``presentation_state_update`` refused -- which is what made unticking
        "Load textures" do nothing while the send itself looked successful.

        Authoring binds through ``set_authoritative_session_id`` because an edit
        session owns the helper and must not be stolen. A preview owns nothing, so
        it simply follows the package.
        """

        normalized = scene_session_id.strip()
        if not normalized:
            scene_path = Path(getattr(resolved, "package_dir", "")) / "dotnet_scene.json"
            try:
                payload = json.loads(scene_path.read_text(encoding="utf-8-sig"))
            except (OSError, TypeError, ValueError):
                return False
            if isinstance(payload, Mapping):
                normalized = str(payload.get("session_id", "") or "").strip()
        if not normalized or normalized == self._session_id:
            return False
        self._session_id = normalized
        return True

    def set_authoritative_session_id(self, session_id: str) -> bool:
        """Bind this controller to a real edit session, adopting a prewarm if one is running.

        A prewarmed authoring helper handshakes before any edit session exists, so
        it is holding a placeholder id. That used to make the binding fail and the
        first Edit Mesh report "authoring session changed while the resident helper
        was active" -- which is why the prewarm could only be started *after* the
        session id was known, i.e. too late to hide the helper's start-up. While
        the session is still provisional the real id replaces it and is
        re-handshaked; while a real session still *owns* the helper nothing may
        take it. Once that session has released it -- see ``clear_preview`` --
        the warm process is handed on rather than held for a session that no
        longer exists.
        """

        normalized = str(session_id or "").strip()
        if self.profile is not DotNetPreviewProfile.AUTHORING or not normalized:
            return False
        if normalized == self._session_id:
            # The same session coming back after a suspend is taking its own
            # helper, so any release it declared on the way out is withdrawn.
            self._session_released = False
            return True
        if self._session_established and not self._session_provisional:
            if self._launch_is_prewarm and self._desired_package is None:
                # A prewarm holding a session it cannot hand back must never be
                # the reason a real edit session is refused. This is the older
                # helper without `authoring_provisional_session_v1`: drop the
                # warm process and let the real package start its own.
                self._discard_warm_process()
                self._session_id = normalized
                return True
            if self._session_released:
                return self._adopt_released_session(normalized)
            return False
        self._session_id = normalized
        if self._session_provisional and self._session_established:
            sent = self._send_authoritative_session_state()
            if sent and self._protocol_ready and self._localization_keys:
                self._send_ui_localization_state()
            return sent
        if self._protocol_ready and self._localization_keys:
            self._send_ui_localization_state()
        return True

    def _adopt_released_session(self, session_id: str) -> bool:
        """Hand a warm helper from a released edit session to the next one.

        The claim taken by ``set_authoritative_session_id`` protects a *live*
        edit session from having its helper stolen. It had no counterpart for
        the session ending, so it outlived its owner: ``clear_preview`` drops
        the package, the leases and the viewport but deliberately leaves the
        process warm for the next mesh, and that warm process stayed bound to a
        session that no longer existed. Every later bind was refused, and
        ``load_package`` turned the refusal into "Close the current editor
        before opening another mesh" -- about an editor the reader had already
        closed. Nothing but killing the helper, i.e. shutting the whole Mesh
        Editor down, ever cleared it, which is exactly the shape the report
        described: the second mesh never loaded.

        Stealing from a live session is still refused by the caller. This is
        only reached once that session has let go.
        """

        previous = self._session_id
        self._session_id = session_id
        self._session_released = False
        if not self._can_send_protocol():
            # No helper is listening, so there is nothing to hand over: the next
            # launch handshakes with the new id from the start.
            return True
        if "authoring_session_handoff_v1" not in self._capabilities:
            # An older helper latches its resident session for the life of the
            # process and cannot be told the owner left, so every correlated
            # message from the new session would be refused as a mismatch --
            # the mesh would appear and then answer nothing. Trading the warm
            # start for a correct one is the bargain the prewarm path above
            # already makes.
            self._discard_warm_process()
            return True
        self._send_json(
            {
                "event": "session_release",
                "session_id": previous,
                "process_generation": self._process_generation,
                "protocol_version": 2,
            }
        )
        sent = self._send_authoritative_session_state()
        if sent and self._protocol_ready and self._localization_keys:
            self._send_ui_localization_state()
        return sent

    def _discard_warm_process(self) -> None:
        """Stop a warm helper without touching the desired-package stream.

        Used by the two paths that decide a resident process cannot serve the
        session now asking for it: an older prewarm holding a placeholder id it
        cannot hand back, and a released session on a helper that cannot be
        handed on. Both want the process gone and the package stream intact.
        """

        process = self._process
        self._process = None
        self._ready_timer.stop()
        self._package_timer.stop()
        self._activation_timer.stop()
        self._pending_activation = None
        self._activation_waiting_for_material_sync = False
        self._activation_material_sync_generation = 0
        self._pending_package_generation = 0
        self._protocol_ready = False
        self._renderer_ready = False
        self._session_established = False
        self._session_provisional = False
        self._session_released = False
        self._active = False
        self._capabilities.clear()
        self._reset_localization_handshake()
        self._clear_prewarm_capture()
        prewarm_path = (
            str(self._prewarm_package.package_dir) if self._prewarm_package is not None else ""
        )
        self._prewarm_package = None
        self._launch_is_prewarm = False
        if process is not None:
            self._send_json_to_process(process, {"event": "close_request"})
            stop_qprocess_async(process)
        if prewarm_path:
            self._release_package_lease(prewarm_path)

    def _send_authoritative_session_state(self) -> bool:
        """Promote the live handshake from the placeholder id to the real one."""

        sent = self._send_json(
            {
                "event": "session_state",
                "session_id": self._session_id,
                "process_generation": self._process_generation,
                "protocol_version": 2,
                "provisional_session": False,
                "revision": 0,
                "edit_revision": 0,
                "history": {"undo": [], "redo": []},
                "selection": {},
            }
        )
        if sent:
            self._session_provisional = False
        return sent

    def set_authoring_rehydrator(
        self,
        callback: Callable[["DotNetPreviewSessionController"], bool] | None,
    ) -> None:
        self._authoring_rehydrator = callback

    def send_authoring_message(self, payload: Mapping[str, object]) -> bool:
        if self.profile is not DotNetPreviewProfile.AUTHORING or not self._can_send_protocol():
            return False
        message = dict(payload)
        message.setdefault("session_id", self._session_id)
        message.setdefault("process_generation", self._process_generation)
        message.setdefault("protocol_version", 2)
        sent = self._send_json(message)
        if sent:
            self._remember_replayable_authoring_state(message)
        return sent

    _SCENE_STATE_KEY = "scene"
    _REPLAYABLE_AUTHORING_EVENTS = {"scene_state_update": _SCENE_STATE_KEY}
    # Only the authoring host knows the live interaction mode; the preview host
    # echoes whatever the package declared, which is always "placement".
    _AUTHORING_OWNED_SCENE_FIELDS = ("interaction_mode", "comparison_mode")

    def _remember_replayable_authoring_state(self, message: Mapping[str, object]) -> None:
        """Keep the replay set in step with what the authoring host actually sent.

        Authoring frames go out through this class rather than
        ``remember_state``, so they never reached the slot ``_replay_resident_state``
        re-asserts after every package load -- and a session that had switched
        the helper into ``mesh_edit`` was dropped back to placement by its own
        replay, taking the Edit Mesh UI with it.
        """
        key = self._REPLAYABLE_AUTHORING_EVENTS.get(
            str(message.get("event", "")).strip().lower()
        )
        if key is None:
            return
        for field in self._AUTHORING_OWNED_SCENE_FIELDS:
            value = str(message.get(field, "") or "").strip()
            if value:
                self._authoring_scene_modes[field] = value
        if self._authoring_rehydrator is not None:
            # The Mesh Editor rehydrator republishes this state through its own
            # request/generation lane. Retaining a controller replay would make
            # the helper compare two independent counters for the same scene.
            self._resident_state.pop(key, None)
            return
        self._store_resident_state(key, str(message.get("event", "")), message)

    @property
    def desired_package_path(self) -> str:
        package = self._desired_package
        return str(package.package_dir) if package is not None else ""

    @property
    def applied_package_path(self) -> str:
        return self._applied_package_path

    @property
    def serving_prewarm_placeholder(self) -> bool:
        """True while the resident helper holds only the procedural warm-up scene.

        A prewarm launch starts the helper on a package nobody asked to see, so
        that the process, JIT and D3D device are warm before the first real
        request. Until a real package has been applied that helper is not a
        resident scene any caller may present: activating it reveals the
        placeholder. `_launch_is_prewarm` alone does not answer this, because it
        is cleared as soon as the renderer reports ready, which can happen before
        any package load.

        An empty applied path is not the whole answer either, and that was the
        gap the reader saw as a triangle in a fresh Mesh Editor. The helper does
        apply the prewarm package, and from that moment the applied path is not
        empty -- so this said "no placeholder" precisely while the procedural
        warm-up triangle was the thing on screen, and `_activate_applied`, which
        asks only for an applied path, revealed it.
        """

        if self._prewarm_package is None:
            return False
        applied = str(self._applied_package_path or "")
        if not applied:
            return True
        return applied == str(getattr(self._prewarm_package, "package_dir", "") or "")

    @property
    def last_event(self) -> Mapping[str, object]:
        return dict(self._last_event)

    def load_package(
        self,
        package: MeshDotNetExperimentPackage | Path | str,
        status_path: Path | str | None = None,
        *,
        reset_view: bool = False,
        force_reload: bool = False,
    ) -> bool:
        if self._closed:
            return False
        try:
            resolved = (
                package
                if isinstance(package, MeshDotNetExperimentPackage)
                else mesh_dotnet_experiment_package_from_path(package, status_path=status_path)
            )
        except (OSError, TypeError, ValueError) as exc:
            self._invalid_retry_package_path = str(package)
            self._invalid_retry_status_path = str(status_path or "")
            self._invalid_retry_reset_view = bool(reset_view)
            detail = f".NET/Vortice preview package is invalid: {exc}"
            self.package_failed.emit(str(package), self._package_generation, detail)
            self._set_state("package_error", detail)
            return False
        self._invalid_retry_package_path = ""
        self._invalid_retry_status_path = ""
        self._invalid_retry_reset_view = False
        identity = self._package_identity(resolved)
        scene_session_id = str(
            getattr(getattr(resolved, "scene_frame", None), "scene_session_id", "") or ""
        ).strip()
        if self.profile is DotNetPreviewProfile.AUTHORING:
            if scene_session_id and not self.set_authoritative_session_id(scene_session_id):
                detail = (
                    ".NET/Vortice authoring package belongs to a different active edit session. "
                    "Close the current editor before opening another mesh."
                )
                self.package_failed.emit(str(resolved.package_dir), self._package_generation, detail)
                self._set_state("package_error", detail)
                return False
        else:
            self._follow_preview_package_session(resolved, scene_session_id)
        if not force_reload and identity == self._desired_package_identity:
            if reset_view:
                self._resident_state.pop("presentation", None)
            if self._visible and identity == self._applied_package_identity:
                self._activate()
                return True
            if (
                self._visible
                and self._can_send_protocol()
                and self._protocol_ready
                and self._renderer_ready
                and self._session_established
                and self._localization_initial_established
                and not self._package_timer.isActive()
            ):
                # The helper consumes every accepted generation even when
                # preparation fails. An explicit retry therefore needs a newer
                # generation; resending the failed one is correctly rejected as
                # stale by the resident package protocol.
                force_reload = True
            else:
                return True

        previous_desired = self.desired_package_path
        self._hold_package_lease(resolved.package_dir)
        # A package generation owns its activation request and any deferred
        # material sync. Replacing that generation must invalidate both before
        # the next package_load_request is sent; otherwise a late material ack
        # for the old package can consume the new package's reveal cycle.
        self._activation_timer.stop()
        self._pending_activation = None
        self._activation_waiting_for_material_sync = False
        self._activation_material_sync_generation = 0
        self._package_generation += 1
        self._desired_package = resolved
        self._desired_package_identity = identity
        if reset_view:
            self._resident_state.pop("presentation", None)
        if (
            previous_desired
            and self._package_key(previous_desired) != self._package_key(resolved.package_dir)
            and self._package_key(previous_desired) != self._package_key(self._applied_package_path)
        ):
            self._release_package_lease(previous_desired)
        self._set_state("preparing", ".NET/Vortice Preview is preparing the selected model…")
        if self._visible:
            if (
                self._launch_is_prewarm
                and not self._renderer_ready
                and self._localization_initial_established
            ):
                if not self._request_resident_package_load():
                    self._await_resident_gates_for_package_load()
            elif self._can_send_protocol():
                self._request_resident_package_load()
            else:
                self.retry_now()
        return True

    def prewarm(
        self,
        package: MeshDotNetExperimentPackage | Path | str,
        status_path: Path | str | None = None,
    ) -> bool:
        """Start the resident helper without consuming a user package generation."""

        if self._closed or self._desired_package is not None or self.is_running:
            return False
        try:
            resolved = (
                package
                if isinstance(package, MeshDotNetExperimentPackage)
                else mesh_dotnet_experiment_package_from_path(package, status_path=status_path)
            )
        except (OSError, TypeError, ValueError):
            return False
        self._prewarm_package = resolved
        self._hold_package_lease(resolved.package_dir)
        self._launch_if_needed()
        return self.is_running

    def clear_preview(self) -> bool:
        if self._closed:
            return False
        # Letting go of the resident scene is also letting go of the session
        # that owned it. The process stays warm on purpose, so without this the
        # claim outlives its owner and the next edit session can never bind.
        # `set_authoritative_session_id` withdraws this again if the same
        # session comes back, so an ordinary suspend and resume costs nothing.
        if (
            self.profile is DotNetPreviewProfile.AUTHORING
            and self._session_established
            and not self._session_provisional
        ):
            self._session_released = True
        self._package_generation += 1
        self._desired_package = None
        self._desired_package_identity = None
        self._applied_package = None
        self._applied_package_identity = None
        self._applied_package_path = ""
        self._applied_package_generation = 0
        self._resident_material_signature = ""
        self._invalid_retry_package_path = ""
        self._invalid_retry_status_path = ""
        self._invalid_retry_reset_view = False
        self._package_timer.stop()
        self._activation_timer.stop()
        self._pending_activation = None
        self._activation_waiting_for_material_sync = False
        self._activation_material_sync_generation = 0
        self._pending_package_generation = 0
        self._deactivate_for_replacement()
        self._release_package_leases()
        self._set_state("empty", "Select a model to open .NET/Vortice Preview.")
        return True

    def reembed(self, parent_hwnd: int) -> bool:
        """Move a running helper into a replacement host window.

        The parent HWND is passed on the helper's command line at launch and was
        never re-read, so when Qt destroyed and recreated the host widget's
        native window -- which it does on a move to a screen at a different
        scale -- the helper stayed a child of a window that was no longer the
        one on screen. A relaunch would be the alternative, and it would drop
        the resident scene and the edit session with it.
        """

        try:
            hwnd = max(0, int(parent_hwnd or 0))
        except (TypeError, ValueError):
            return False
        if self._closed or hwnd <= 0 or not self._can_send_protocol():
            return False
        return bool(self._send_json({"event": "reembed_request", "parent_hwnd": hwnd}))

    def set_visible(self, visible: bool) -> None:
        self._visible = bool(visible)
        if self._closed:
            return
        if not self._visible:
            self._retry_timer.stop()
            self._activation_timer.stop()
            self._pending_activation = None
            self._activation_waiting_for_material_sync = False
            self._activation_material_sync_generation = 0
            self._activation_retry_count = 0
            self._send_json({"event": "deactivate_request"})
            self._active = False
            self._set_state("inactive", ".NET/Vortice Preview paused while hidden.")
            return
        if (
            self._launch_is_prewarm
            and self._session_established
            and self._localization_initial_established
            and not self._renderer_ready
        ):
            if self._desired_package is None:
                # Becoming visible with nothing selected must not present the
                # procedural prewarm scene: the helper stays resident and warm,
                # but showing its placeholder triangle only to replace it when
                # the real package arrives reads as a flicker.
                return
            if not self._request_resident_package_load():
                self._await_resident_gates_for_package_load()
        if self._desired_package is None:
            self._set_state("empty", "Select a model to open .NET/Vortice Preview.")
            return
        self._set_state("resuming", ".NET/Vortice Preview is resuming…")
        if self._process is None or not qprocess_is_running(self._process):
            self.retry_now()
            return
        if (
            self._applied_package_path
            and self._session_established
            and self._localization_initial_established
        ):
            if self._applied_package_identity != self._desired_package_identity:
                # Activating first reveals the helper's window on whatever
                # package is still resident -- the procedural prewarm scene, or
                # the mesh opened before this one -- and only then asks for the
                # one that was actually selected. That is the placeholder
                # triangle at Mesh Editor start: the wrong model, shown for as
                # long as the real load takes, in a window that was revealed
                # specifically to show something else. `_activate_applied` does
                # not check identity, which is what let this through; the load
                # path activates from `_accept_applied_package` once the right
                # package has landed, so there is nothing to reveal early for.
                if not self._request_resident_package_load():
                    self._await_resident_gates_for_package_load()
                return
            elif self._activate_applied():
                return
        elif self._request_resident_package_load():
            return
        # Becoming visible again must not end in silence. Every branch above can
        # decline without sending anything -- a handshake gate that is still
        # down, a package request the helper already applied -- and the panel
        # then keeps showing "paused while hidden" over a perfectly healthy
        # resident scene, with no way back except restarting the editor. That is
        # what leaving Mesh Editor for another tab and returning did.
        #
        # Asking the helper to reveal what it is already holding is the right
        # answer here and is idempotent: it answers `activated`, which is what
        # clears the panel. A helper still holding only the procedural warm-up
        # scene is the one case that must stay hidden, and it is excluded rather
        # than asked and refused.
        if self._applied_package_path and not self.serving_prewarm_placeholder:
            self._request_activation(self._applied_package)

    def retry_now(self) -> None:
        if self._closed or not self._visible:
            return
        if self._invalid_retry_package_path:
            self.load_package(
                self._invalid_retry_package_path,
                self._invalid_retry_status_path or None,
                reset_view=self._invalid_retry_reset_view,
                force_reload=True,
            )
            return
        if self._desired_package is None:
            return
        self._retry_timer.stop()
        if self._process is not None and qprocess_is_running(self._process):
            if self._can_send_protocol():
                self.load_package(self._desired_package, force_reload=True)
            return
        self._launch_if_needed()

    def remember_state(self, key: str, event: str, payload: Mapping[str, object]) -> bool:
        normalized_key = str(key or event).strip().lower()
        body = dict(payload)
        body.pop("event", None)
        if normalized_key == self._SCENE_STATE_KEY:
            # This frame's mode fields are the package's boot defaults, not the
            # live mode: without the overlay a placement nudge during Edit Mesh
            # drops the helper out of it, on this send and on the reload replay.
            body.update(self._authoring_scene_modes)
        self._store_resident_state(normalized_key, event, body)
        if (
            self._session_established
            and self._renderer_ready
            and self._localization_initial_established
        ):
            return self.send_correlated(event, body) > 0
        return True

    def _store_resident_state(self, key: str, event: str, payload: Mapping[str, object]) -> None:
        body = dict(payload)
        body.pop("event", None)
        self._resident_state[str(key).strip().lower()] = (str(event), body)

    def forget_state(self, key: str) -> None:
        self._resident_state.pop(str(key or "").strip().lower(), None)

    def send_correlated(self, event: str, payload: Mapping[str, object] | None = None) -> int:
        if not (
            self._session_established
            and self._localization_initial_established
        ):
            return 0
        self._protocol_request_id += 1
        request_id = self._protocol_request_id
        message = dict(payload or {})
        message.update(
            {
                "event": str(event),
                "session_id": self._session_id,
                "request_id": request_id,
                "base_revision": 0,
                "revision": 0,
                "edit_revision": 0,
                "process_generation": self._process_generation,
                "protocol_version": 2,
            }
        )
        return request_id if self._send_json(message) else 0

    def request_capture(self, output_path: Path | str, *, width: int = 512, height: int = 512) -> bool:
        package = self._desired_package
        if package is None or not self._session_established:
            return False
        # The helper only writes captures under the output directory it was launched
        # with; a package loaded into the resident process later has its own output
        # directory, which the helper refuses ("Capture output must remain inside the
        # package output directory"). Ask under the launch package's, recreated if the
        # package was cleaned up meanwhile; the file is moved to `output_path` anyway.
        launch = str(self._launch_package_path or "")
        capture_root = Path(launch) / "output" if launch and self._process is not None else package.output_dir
        capture_dir = capture_root / "captures"
        try:
            capture_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        internal_path = capture_dir / f"capture_{self._protocol_request_id + 1:08d}.png"
        request_id = self.send_correlated(
            "capture_request",
            {
                "output_path": str(internal_path),
                "width": max(64, min(2048, int(width))),
                "height": max(64, min(2048, int(height))),
            },
        )
        if request_id <= 0:
            return False
        self._pending_captures[request_id] = (internal_path, Path(output_path).expanduser())
        return True

    def hold_package_lease(self, package_dir: Path | str) -> bool:
        before = len(self._package_leases)
        self._hold_package_lease(Path(package_dir))
        return len(self._package_leases) > before or self._package_key(package_dir) in self._package_leases

    def release_package_lease(self, package_dir: Path | str) -> None:
        self._release_package_lease(package_dir)

    def retain_package_lease(self, package_dir: Path | str) -> None:
        self._retain_package_leases({str(package_dir)})

    def release_package_leases(self) -> None:
        self._release_package_leases()

    def deactivate(self) -> None:
        self.set_visible(False)

    def activate(self) -> None:
        self.set_visible(True)

    def request_activation(self, *, material_signature: str | None = None) -> bool:
        """Reveal the resident package through the controller's correlation owner.

        Mesh Editor resident reuse may need to request a newer material
        signature than the helper currently acknowledges. The controller still
        owns the activation id, package generation, pending state and watchdog;
        callers provide only that desired signature.
        """

        if self._closed:
            return False
        self._visible = True
        return self._request_activation(
            self._applied_package,
            material_signature=material_signature,
        )

    def close(self) -> None:
        if self._closed:
            return
        if not self._terminate_on_close:
            self.deactivate()
            return
        self.shutdown()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._retry_timer.stop()
        self._ready_timer.stop()
        self._package_timer.stop()
        self._activation_timer.stop()
        self._pending_activation = None
        self._activation_waiting_for_material_sync = False
        self._activation_material_sync_generation = 0
        self._pending_package_generation = 0
        process = self._process
        self._process = None
        if process is not None:
            self._send_json_to_process(process, {"event": "close_request"})
            stop_qprocess_async(process)
        signal = getattr(self._ui_localizer, "language_changed", None)
        if signal is not None:
            try:
                signal.disconnect(self._handle_ui_language_changed)
            except (RuntimeError, TypeError):
                pass
        self._ui_localizer = None
        self._reset_localization_handshake()
        self._release_package_leases()
        self._pending_captures.clear()
        self._clear_prewarm_capture()
        self._prewarm_package = None
        self._launch_is_prewarm = False
        self._set_state("closed", ".NET/Vortice Preview closed.")

    def _launch_if_needed(self) -> None:
        package = self._desired_package or self._prewarm_package
        prewarm_launch = self._desired_package is None and self._prewarm_package is not None
        if self._closed or package is None or (not self._visible and not prewarm_launch):
            return
        if self._process is not None and qprocess_is_running(self._process):
            return
        parent_hwnd = self._safe_host_hwnd()
        if parent_hwnd <= 0:
            self._schedule_retry("Preview host window is not ready.", static_failure=False)
            return
        resolution = resolve_mesh_dotnet_experiment_editor(self._configured_executable)
        executable = Path(resolution.resolved_path).expanduser() if resolution.resolved_path else Path()
        require_manifest = bool(getattr(sys, "frozen", False) or (executable.parent / "cdmw-mesh-dotnet-editor.manifest.json").is_file())
        required_capabilities = self._required_protocol_capabilities()
        blockers = mesh_dotnet_helper_static_provenance_blockers(
            executable,
            require_manifest=require_manifest,
            required_capabilities=required_capabilities,
        )
        if blockers:
            self._schedule_retry(
                ".NET/Vortice helper was not executed: " + "; ".join(blockers),
                static_failure=True,
            )
            return
        try:
            program, arguments = mesh_dotnet_experiment_command(
                executable,
                package,
                embedded_parent_hwnd=parent_hwnd,
                profile=self.profile.value,
                prewarm_launch=prewarm_launch,
                direct_authoring=self._direct_authoring,
            )
        except (OSError, TypeError, ValueError) as exc:
            self._schedule_retry(f"Could not configure .NET/Vortice Preview: {exc}", static_failure=False)
            return

        process = self._process_factory(self)
        self._process_generation += 1
        generation = self._process_generation
        self._launch_package_generation = self._package_generation
        self._launch_package_path = str(package.package_dir)
        self._launch_is_prewarm = prewarm_launch
        self._process = process
        self._executable = Path(program)
        self._protocol_ready = False
        self._renderer_ready = False
        self._session_established = False
        self._session_provisional = False
        self._session_released = False
        self._pending_package_generation = 0
        self._active = False
        self._resident_material_signature = ""
        self._capabilities.clear()
        self._reset_localization_handshake()
        self._clear_prewarm_capture()
        self._stdout_buffer = b""
        self._stdout_tail = ""
        self._stderr_tail = ""
        try:
            process.setProgram(program)
            process.setArguments(arguments)
            process.setWorkingDirectory(str(package.package_dir))
            process.setProcessChannelMode(QProcess.SeparateChannels)
            process.readyReadStandardOutput.connect(
                lambda target=process, token=generation: self._read_stdout(target, token)
            )
            process.readyReadStandardError.connect(
                lambda target=process, token=generation: self._read_stderr(target, token)
            )
            process.started.connect(lambda target=process, token=generation: self._process_started(target, token))
            process.finished.connect(
                lambda exit_code=0, exit_status=0, target=process, token=generation: self._process_finished(
                    target, token, int(exit_code), exit_status
                )
            )
            process.errorOccurred.connect(
                lambda error, target=process, token=generation: self._process_error(target, token, error)
            )
            process.start()
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            if self._process is process:
                self._process = None
            stop_qprocess_async(process)
            self._schedule_retry(f".NET/Vortice Preview launch failed: {exc}", static_failure=False)
            return
        self._ready_timer.start(_READY_TIMEOUT_MS)
        self._set_state("launching", ".NET/Vortice Preview is starting…")

    def _process_started(self, process: object, generation: int) -> None:
        if not self._is_current_process(process, generation):
            return
        self._set_state("connecting", ".NET/Vortice Preview is connecting…")

    def _process_finished(self, process: object, generation: int, exit_code: int, exit_status: object) -> None:
        if not self._is_current_process(process, generation):
            self._delete_process_later(process)
            return
        self._read_stdout(process, generation)
        self._read_stderr(process, generation)
        self._process = None
        self._ready_timer.stop()
        self._package_timer.stop()
        self._activation_timer.stop()
        self._pending_activation = None
        self._activation_waiting_for_material_sync = False
        self._activation_material_sync_generation = 0
        self._pending_package_generation = 0
        self._protocol_ready = False
        self._renderer_ready = False
        self._session_established = False
        self._session_provisional = False
        self._session_released = False
        self._reset_localization_handshake()
        self._clear_prewarm_capture()
        self._active = False
        self._prewarm_package = None
        self._launch_is_prewarm = False
        self._delete_process_later(process)
        self._retain_package_leases({self.desired_package_path})
        if not self._closed and self._visible and self._desired_package is not None:
            details = self._stderr_tail.strip() or self._stdout_tail.strip()
            suffix = f" ({details[-400:]})" if details else ""
            self._schedule_retry(
                f".NET/Vortice Preview exited with code {exit_code}{suffix}",
                static_failure=False,
            )

    def _process_error(self, process: object, generation: int, error: object) -> None:
        if not self._is_current_process(process, generation):
            return
        try:
            detail = str(process.errorString() or error)
        except (AttributeError, RuntimeError):
            detail = str(error)
        if not qprocess_is_running(process):
            self._fail_current_process(f".NET/Vortice Preview process error: {detail}", static_failure=False)

    def _read_stdout(self, process: object, generation: int) -> None:
        if not self._is_current_process(process, generation):
            return
        try:
            chunk = bytes(process.readAllStandardOutput())
        except (AttributeError, RuntimeError, TypeError):
            return
        if not chunk:
            return
        self._stdout_tail = append_bounded_text(self._stdout_tail, chunk.decode("utf-8", errors="replace"))
        self._stdout_buffer += chunk
        if len(self._stdout_buffer) > DOTNET_PROTOCOL_BUFFER_LIMIT:
            self._fail_current_process(".NET/Vortice protocol buffer exceeded its safety limit.", static_failure=False)
            return
        while b"\n" in self._stdout_buffer:
            raw_line, self._stdout_buffer = self._stdout_buffer.split(b"\n", 1)
            if len(raw_line) > DOTNET_PROTOCOL_LINE_LIMIT:
                self._fail_current_process(".NET/Vortice protocol line exceeded its safety limit.", static_failure=False)
                return
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if isinstance(payload, Mapping):
                self._handle_protocol_event(dict(payload), generation)

    def _read_stderr(self, process: object, generation: int) -> None:
        if not self._is_current_process(process, generation):
            return
        try:
            chunk = bytes(process.readAllStandardError()).decode("utf-8", errors="replace")
        except (AttributeError, RuntimeError, TypeError):
            return
        if chunk:
            self._stderr_tail = append_bounded_text(self._stderr_tail, chunk)

    def _announce_renderer_ready(self) -> None:
        if (
            not self._renderer_ready
            or self._renderer_ready_announced
            or not self._localization_initial_established
        ):
            return
        self._renderer_ready_announced = True
        self._ready_timer.stop()
        self.renderer_ready.emit(dict(self._renderer_ready_payload or {}))

    def _handle_protocol_event(self, payload: dict[str, object], generation: int) -> None:
        if generation != self._process_generation:
            return
        event = str(payload.get("event", payload.get("type", "")) or "").strip().lower()
        if not event:
            return
        if event in {"activated", "material_state_applied", "material_parameter_applied"}:
            self._remember_resident_material_signature(payload)
        if event == "material_sync_required" and self._pending_activation is not None:
            # The helper deliberately withholds `activated` until Python has
            # compiled and published the requested resident material state.
            # That work can legitimately outlive the ordinary 10-second
            # re-embed watchdog. Give that bounded work its own deadline instead
            # of killing a healthy process halfway through the sync or pausing
            # recovery forever when compilation fails before the helper can ack.
            self._activation_waiting_for_material_sync = True
            self._activation_material_sync_generation = 0
            self._activation_timer.start(_MATERIAL_SYNC_TIMEOUT_MS)
        elif (
            event == "material_state_started"
            and self._pending_activation is not None
            and self._activation_waiting_for_material_sync
        ):
            self._remember_activation_material_sync_generation(payload)
        elif (
            event in {"material_state_applied", "material_state_failed"}
            and self._pending_activation is not None
            and self._activation_waiting_for_material_sync
            and self._material_sync_ack_matches_pending_activation(payload)
        ):
            self._activation_waiting_for_material_sync = False
            self._activation_material_sync_generation = 0
            self._activation_timer.start(_READY_TIMEOUT_MS)
        if event == "ready":
            if not self._handle_renderer_ready(payload):
                return
            self._last_event = dict(payload)
            self.protocol_event.emit(dict(payload))
            return
        if event == "activated":
            pending = self._pending_activation
            if pending is None:
                return
            request_id = int(payload.get("activation_request_id", 0) or 0)
            process_generation = int(payload.get("process_generation", 0) or 0)
            package_generation = int(payload.get("package_generation", 0) or 0)
            if request_id > 0 and request_id != pending["request_id"]:
                return
            if process_generation > 0 and process_generation != pending["process_generation"]:
                return
            if package_generation > 0 and package_generation != pending["package_generation"]:
                return
        self._last_event = dict(payload)
        self.protocol_event.emit(dict(payload))
        if event == "protocol_ready":
            self._handle_protocol_ready(payload)
        elif event == "ui_localization_state_ack":
            self._handle_ui_localization_ack(payload)
        elif event == "preview_session_state_ack":
            if str(payload.get("status", "") or "").lower() == "applied" and self._event_process_matches(payload):
                self._session_established = True
                self._maybe_finish_launch()
        elif event == "package_load_applied":
            self._handle_package_applied(payload)
        elif event == "package_load_failed":
            self._handle_package_failed(payload)
        elif event == "view_state_changed":
            self.view_state_changed.emit(dict(payload))
        elif event == "part_pick_result":
            self.part_pick_result.emit(dict(payload))
        elif event == "capture_result":
            self._handle_capture_result(payload)
        elif event == "activated":
            self._activation_timer.stop()
            self._pending_activation = None
            self._activation_waiting_for_material_sync = False
            self._activation_material_sync_generation = 0
            self._activation_retry_count = 0
            self._active = True
            self._retry_attempt = 0
            self._set_state("ready", ".NET/Vortice Preview")
        elif event == "deactivated":
            self._active = False
            if self._visible and self._applied_package_path:
                self._request_activation(self._applied_package)
        elif event == "error":
            # Helper-level request errors (invalid tool state, stale sessions,
            # malformed commands, and similar protocol rejections) do not
            # imply that the process or D3D device is unhealthy. Consumers get
            # the original event above and can offer a retry without discarding
            # the resident scene. An actual helper exit or QProcess/device
            # failure still follows the process retry path.
            return

    def _handle_protocol_ready(self, payload: Mapping[str, object]) -> None:
        if str(payload.get("profile", "") or "").strip().lower() != self.profile.value:
            self._fail_current_process(".NET/Vortice helper started with the wrong profile.", static_failure=True)
            return
        manifest_path = self._executable.parent / "cdmw-mesh-dotnet-editor.manifest.json"
        blockers = mesh_dotnet_helper_provenance_blockers(
            self._executable,
            payload,
            require_manifest=bool(getattr(sys, "frozen", False) or manifest_path.is_file()),
            required_capabilities=self._required_protocol_capabilities(),
        )
        if blockers:
            self._fail_current_process(
                ".NET/Vortice helper provenance blocked: " + "; ".join(blockers),
                static_failure=True,
            )
            return
        raw_capabilities = payload.get("capabilities", ())
        if isinstance(raw_capabilities, Sequence) and not isinstance(raw_capabilities, (str, bytes)):
            self._capabilities = {str(value) for value in raw_capabilities}
        if "ui_localization_v1" in self._capabilities:
            raw_keys = payload.get("localization_keys", ())
            if (
                not isinstance(raw_keys, Sequence)
                or isinstance(raw_keys, (str, bytes))
                or not raw_keys
                or len(raw_keys) > 10_000
                or any(not isinstance(value, str) or not value for value in raw_keys)
            ):
                self._fail_current_process(
                    ".NET/Vortice helper localization key manifest is invalid.",
                    static_failure=True,
                )
                return
            localization_keys = tuple(str(value) for value in raw_keys)
            if localization_keys != tuple(sorted(set(localization_keys))):
                self._fail_current_process(
                    ".NET/Vortice helper localization keys are not unique and sorted.",
                    static_failure=True,
                )
                return
            advertised_hash = str(
                payload.get("localization_key_manifest_hash", "") or ""
            )
            expected_hash = self._localization_manifest_hash(localization_keys)
            if advertised_hash != expected_hash:
                self._fail_current_process(
                    ".NET/Vortice helper localization manifest hash did not match its keys.",
                    static_failure=True,
                )
                return
            from cdmw.ui.localization_catalogs_v2 import SOURCE_STRING_CATALOGUE

            unknown_keys = set(localization_keys) - set(SOURCE_STRING_CATALOGUE)
            if unknown_keys:
                self._fail_current_process(
                    ".NET/Vortice helper localization manifest is newer than the host catalog.",
                    static_failure=True,
                )
                return
            self._localization_keys = localization_keys
            self._localization_key_manifest_hash = advertised_hash
            self._localization_initial_established = False
        else:
            self._localization_keys = ()
            self._localization_key_manifest_hash = ""
            self._localization_initial_established = True
        self._protocol_ready = True
        if self._localization_keys and not self._send_ui_localization_state():
            if self._process is not None:
                self._fail_current_process(
                    "Could not establish .NET/Vortice interface localization.",
                    static_failure=False,
                )
            return
        self._announce_renderer_ready()
        if self.profile is DotNetPreviewProfile.PREVIEW:
            sent = self._send_json(
                {
                    "event": "preview_session_state",
                    "session_id": self._session_id,
                    "process_generation": self._process_generation,
                    "protocol_version": 2,
                }
            )
            if not sent:
                self._fail_current_process("Could not establish the preview session.", static_failure=False)
        else:
            # A prewarm launch has no edit session to name yet, so it handshakes
            # with a placeholder the first real Edit Mesh is allowed to replace.
            # Gated on the capability rather than required: an older helper still
            # runs, it just cannot be prewarmed ahead of the session.
            provisional = bool(
                self._launch_is_prewarm
                and self._desired_package is None
                and "authoring_provisional_session_v1" in self._capabilities
            )
            sent = self._send_json(
                {
                    "event": "session_state",
                    "session_id": self._session_id,
                    "process_generation": self._process_generation,
                    "protocol_version": 2,
                    "provisional_session": provisional,
                    "revision": 0,
                    "edit_revision": 0,
                    "history": {"undo": [], "redo": []},
                    "selection": {},
                }
            )
            self._session_established = bool(sent)
            self._session_provisional = bool(sent and provisional)
            if not sent:
                self._fail_current_process("Could not establish the authoring session.", static_failure=False)
                return
            self._maybe_finish_launch()

    def _handle_renderer_ready(self, payload: Mapping[str, object]) -> bool:
        if self._renderer_ready:
            return False
        if str(payload.get("profile", "") or "").strip().lower() != self.profile.value:
            self._fail_current_process(".NET/Vortice renderer reported the wrong profile.", static_failure=True)
            return False
        blockers = mesh_dotnet_renderer_blockers(
            payload,
            embedded=True,
        )
        if blockers:
            self._fail_current_process(
                ".NET/Vortice renderer was rejected: " + "; ".join(blockers),
                static_failure=False,
            )
            return False
        self._renderer_ready = True
        self._renderer_ready_payload = dict(payload)
        self._announce_renderer_ready()
        self._maybe_finish_launch()
        return True

    def _maybe_finish_launch(self) -> None:
        if (
            self._launch_is_prewarm
            and self._protocol_ready
            and self._session_established
            and self._localization_initial_established
            and not self._renderer_ready
        ):
            # A hidden embedded HWND cannot present its first frame yet. The
            # helper and D3D device are nevertheless resident after the
            # protocol/session handshake, so keep them alive until a real
            # request makes the host visible and the correlated Ready arrives.
            self._request_prewarm_capture()
            if self._visible and self._desired_package is not None:
                if not self._request_resident_package_load():
                    self._await_resident_gates_for_package_load()
            else:
                self._ready_timer.stop()
                self._set_state("prewarmed", ".NET/Vortice Preview is ready for a model.")
            return
        if not (
            self._protocol_ready
            and self._renderer_ready
            and self._session_established
            and self._localization_initial_established
        ):
            return
        if self._launch_is_prewarm:
            self._launch_is_prewarm = False
            if self._desired_package is not None:
                self._request_resident_package_load()
            else:
                self._send_json({"event": "deactivate_request"})
                self._active = False
                self._set_state("prewarmed", ".NET/Vortice Preview is ready for a model.")
            return
        if (
            self._launch_package_generation != self._package_generation
            or self._launch_package_path != self.desired_package_path
        ):
            self._request_resident_package_load()
            return
        self._accept_applied_package(self._launch_package_path, self._launch_package_generation)

    def _request_resident_package_load(self) -> bool:
        package = self._desired_package
        if package is None or not self._can_send_protocol():
            return False
        if not (
            self._protocol_ready
            and self._session_established
            and self._localization_initial_established
        ):
            return False
        if not self._renderer_ready and not self._launch_is_prewarm:
            return False
        if (
            self._applied_package_path == self.desired_package_path
            and self._applied_package_generation == self._package_generation
            and self._applied_package_identity == self._desired_package_identity
        ):
            return True
        if (
            self._pending_package_generation == self._package_generation
            and self._package_timer.isActive()
        ):
            return True
        self._package_request_id += 1
        request_id = self._package_request_id
        generation = self._package_generation
        sent = self._send_json(
            {
                "event": "package_load_request",
                "request_id": request_id,
                "generation": generation,
                "package_path": str(package.package_dir),
            }
        )
        if sent:
            self._pending_package_generation = generation
            self._package_timer.start(_PACKAGE_TIMEOUT_MS)
            self._set_state("preparing", ".NET/Vortice Preview is loading the selected model…")
        return sent

    def _handle_package_applied(self, payload: Mapping[str, object]) -> None:
        if not self._package_event_is_current(payload):
            return
        self._package_timer.stop()
        self._pending_package_generation = 0
        self._accept_applied_package(self.desired_package_path, self._package_generation)

    def _handle_package_failed(self, payload: Mapping[str, object]) -> None:
        if not self._package_event_is_current(payload):
            return
        message = str(payload.get("message", payload.get("reason", "Package load failed.")) or "Package load failed.")
        self._fail_current_package(message)

    def _accept_applied_package(self, package_path: str, generation: int) -> None:
        if generation != self._package_generation or package_path != self.desired_package_path:
            return
        self._applied_package_path = package_path
        self._applied_package_generation = generation
        self._applied_package = self._desired_package
        self._applied_package_identity = self._desired_package_identity
        self._resident_material_signature = str(
            getattr(self._applied_package, "material_signature", "") or ""
        )
        self._retain_package_leases({package_path})
        self._replay_resident_state()
        if self.profile is DotNetPreviewProfile.AUTHORING:
            self.rehydrate_requested.emit(self._process_generation)
            if self._authoring_rehydrator is not None:
                try:
                    if not bool(self._authoring_rehydrator(self)):
                        self._fail_current_process(
                            "Authoritative Mesh Editor state could not be restored.",
                            static_failure=False,
                        )
                        return
                except Exception as exc:
                    self._fail_current_process(
                        f"Authoritative Mesh Editor state restore failed: {exc}",
                        static_failure=False,
                    )
                    return
        self.package_applied.emit(package_path, generation)
        if self._visible:
            self._activate()

    def _replay_resident_state(self) -> None:
        for _key, (event, payload) in tuple(self._resident_state.items()):
            self.send_correlated(event, payload)

    def _activate(self) -> bool:
        if not self._visible or self._applied_package_path != self.desired_package_path:
            return False
        return self._request_activation(self._desired_package)

    def _activate_applied(self) -> bool:
        # Activating reveals whatever the helper currently holds. If that is
        # still the procedural warm-up triangle, revealing it shows the reader a
        # model nobody asked for in place of the one they opened.
        if not self._visible or not self._applied_package_path or self.serving_prewarm_placeholder:
            return False
        return self._request_activation(self._applied_package)

    def _request_activation(
        self,
        package: object | None,
        *,
        material_signature: str | None = None,
    ) -> bool:
        if not self._visible or not self._applied_package_path or self.serving_prewarm_placeholder:
            return False
        if self._pending_activation is None:
            self._activation_retry_count = 0
        self._activation_request_id += 1
        requested_material_signature = (
            str(material_signature or "")
            if material_signature is not None
            else self._resident_material_signature
            or str(getattr(package, "material_signature", "") or "")
        )
        pending = {
            "request_id": self._activation_request_id,
            "process_generation": self._process_generation,
            "package_generation": self._applied_package_generation,
            "material_signature": requested_material_signature,
        }
        sent = self._send_json(
            {
                "event": "activate_request",
                "activation_request_id": pending["request_id"],
                "process_generation": pending["process_generation"],
                "package_generation": pending["package_generation"],
                "material_signature": requested_material_signature,
            }
        )
        if not sent:
            return False
        self._pending_activation = pending
        self._activation_waiting_for_material_sync = False
        self._activation_material_sync_generation = 0
        self._activation_timer.start(_READY_TIMEOUT_MS)
        self._set_state("resuming", ".NET/Vortice Preview is resuming…")
        return True

    def _remember_resident_material_signature(self, payload: Mapping[str, object]) -> None:
        signature = str(payload.get("material_signature", "") or "").strip()
        if not signature or not self._applied_package_path:
            return
        try:
            process_generation = int(payload.get("process_generation", 0) or 0)
            package_generation = int(payload.get("package_generation", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return
        if process_generation > 0 and process_generation != self._process_generation:
            return
        if package_generation > 0 and package_generation != self._applied_package_generation:
            return
        self._resident_material_signature = signature

    def _material_sync_ack_matches_pending_activation(
        self,
        payload: Mapping[str, object],
    ) -> bool:
        pending = self._pending_activation
        if pending is None:
            return False
        try:
            process_generation = int(payload.get("process_generation", 0) or 0)
            package_generation = int(payload.get("package_generation", 0) or 0)
            material_generation = int(payload.get("generation", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return False
        return (
            self._activation_material_sync_generation > 0
            and material_generation == self._activation_material_sync_generation
            and not (
                process_generation > 0
                and process_generation != pending["process_generation"]
                or package_generation > 0
                and package_generation != pending["package_generation"]
            )
        )

    def _remember_activation_material_sync_generation(
        self,
        payload: Mapping[str, object],
    ) -> None:
        pending = self._pending_activation
        if pending is None:
            return
        signature = str(payload.get("material_signature", "") or "").strip()
        if not signature:
            return
        try:
            process_generation = int(payload.get("process_generation", 0) or 0)
            package_generation = int(payload.get("package_generation", 0) or 0)
            material_generation = int(payload.get("generation", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return
        if process_generation > 0 and process_generation != pending["process_generation"]:
            return
        if package_generation > 0 and package_generation != pending["package_generation"]:
            return
        if material_generation > self._activation_material_sync_generation:
            # This event is emitted only after the helper has requested a
            # material sync. It identifies the authoritative publication that
            # answers that request, which can legitimately differ from the
            # signature carried by the already-queued activate_request.
            pending["material_signature"] = signature
            self._activation_material_sync_generation = material_generation

    def _await_resident_gates_for_package_load(self) -> None:
        """A real package is wanted but a handshake gate is still down.

        This used to activate the prewarm scene instead, which is what flashed
        the placeholder triangle at Mesh Editor start: the helper revealed its
        procedural warm-up model, then replaced it the moment the load request
        could be sent. Every gate re-runs `_maybe_finish_launch` when it
        arrives, so the load fires at the first possible moment without
        showing anything; this only arms the watchdog, so a helper stuck
        mid-handshake still fails loudly instead of idling hidden.
        """

        self._ready_timer.start(_READY_TIMEOUT_MS)
        self._set_state("preparing", ".NET/Vortice Preview is preparing the selected model…")

    def _deactivate_for_replacement(self) -> None:
        if self._process is not None and qprocess_is_running(self._process):
            self._send_json({"event": "deactivate_request"})
        self._active = False

    def _handle_capture_result(self, payload: Mapping[str, object]) -> None:
        try:
            request_id = int(payload.get("request_id", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            request_id = 0
        if request_id == self._prewarm_capture_request_id:
            self._clear_prewarm_capture()
            if str(payload.get("status", "") or "").strip().lower() == "captured":
                self._set_state("prewarmed", ".NET/Vortice Preview is GPU-warmed and ready for a model.")
            self.capture_completed.emit(dict(payload))
            return
        paths = self._pending_captures.pop(request_id, None)
        result = dict(payload)
        if paths is not None:
            internal_path, target_path = paths
            ok = str(payload.get("status", "") or "").lower() == "captured" and internal_path.is_file()
            if ok:
                try:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    atomic_copy_file(internal_path, target_path)
                    result["requested_output_path"] = str(target_path)
                except OSError as exc:
                    result["status"] = "error"
                    result["message"] = f"Could not publish capture: {exc}"
            try:
                internal_path.unlink(missing_ok=True)
            except OSError:
                pass
        self.capture_completed.emit(result)

    def _request_prewarm_capture(self) -> bool:
        package = self._prewarm_package
        if package is None or not self._session_established:
            return False
        if self._prewarm_capture_request_id > 0:
            return True
        capture_dir = package.output_dir / "captures"
        try:
            capture_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        capture_path = capture_dir / f"prewarm_{self._process_generation:08d}.png"
        request_id = self.send_correlated(
            "capture_request",
            {
                "output_path": str(capture_path),
                "width": 64,
                "height": 64,
            },
        )
        if request_id <= 0:
            return False
        self._prewarm_capture_request_id = request_id
        self._prewarm_capture_path = capture_path
        return True

    def _clear_prewarm_capture(self) -> None:
        capture_path = self._prewarm_capture_path
        self._prewarm_capture_request_id = 0
        self._prewarm_capture_path = None
        if capture_path is None:
            return
        try:
            capture_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _handle_ready_timeout(self) -> None:
        timer_active = self._ready_timer.isActive()
        renderer_already_ready = bool(
            self._protocol_ready
            and self._renderer_ready
            and self._session_established
            and self._localization_initial_established
        )
        if timer_active or renderer_already_ready:
            # QTimer can already have queued its timeout callback when another
            # readiness gate stops or restarts the single-shot timer. A callback
            # from that superseded deadline must not kill the current process;
            # this is especially visible in a one-file package, where extraction
            # makes the prewarm-to-real-package transition overlap the deadline.
            self.protocol_event.emit(
                {
                    "event": "ready_watchdog_ignored",
                    "reason": (
                        "superseded_timer"
                        if timer_active
                        else "renderer_already_ready"
                    ),
                    "process_generation": self._process_generation,
                    "package_generation": self._package_generation,
                    "protocol_ready": self._protocol_ready,
                    "renderer_ready": self._renderer_ready,
                    "session_established": self._session_established,
                    "localization_established": self._localization_initial_established,
                    "timer_active": timer_active,
                }
            )
            return
        self.protocol_event.emit(
            {
                "event": "ready_watchdog_expired",
                "process_generation": self._process_generation,
                "package_generation": self._package_generation,
                "protocol_ready": self._protocol_ready,
                "renderer_ready": self._renderer_ready,
                "session_established": self._session_established,
                "localization_established": self._localization_initial_established,
                "timer_active": False,
            }
        )
        self._fail_current_process(".NET/Vortice Preview did not become ready in time.", static_failure=False)

    def _handle_activation_timeout(self) -> None:
        if self._pending_activation is None or not self._visible:
            return
        if self._activation_waiting_for_material_sync and self._activation_timer.isActive():
            # A timeout already queued before `material_sync_required` may still
            # be delivered after the timer was restarted. Only the real bounded
            # sync deadline fires with the single-shot timer inactive.
            return
        if self._activation_waiting_for_material_sync:
            self._activation_waiting_for_material_sync = False
            self._activation_material_sync_generation = 0
            self._pending_activation = None
            self._fail_current_process(
                ".NET/Vortice material synchronization did not finish in time.",
                static_failure=False,
            )
            return
        if self._activation_retry_count < 1 and self.is_running:
            self._activation_retry_count += 1
            if self._request_activation(self._applied_package):
                return
        self._pending_activation = None
        self._fail_current_process(
            ".NET/Vortice Preview did not reactivate in time.",
            static_failure=False,
        )

    def _handle_package_timeout(self) -> None:
        self._fail_current_package("Package replacement timed out.")

    def _fail_current_package(self, message: str) -> None:
        self._package_timer.stop()
        self._pending_package_generation = 0
        detail = str(message or "Package load failed.")
        self.package_failed.emit(self.desired_package_path, self._package_generation, detail)
        self._set_state(
            "package_error",
            f".NET/Vortice package load failed: {detail} The current model was kept; retry when ready.",
        )

    def _fail_current_process(self, reason: str, *, static_failure: bool) -> None:
        process = self._process
        self._process = None
        self._ready_timer.stop()
        self._package_timer.stop()
        self._activation_timer.stop()
        self._pending_activation = None
        self._activation_waiting_for_material_sync = False
        self._activation_material_sync_generation = 0
        self._protocol_ready = False
        self._renderer_ready = False
        self._session_established = False
        self._session_provisional = False
        self._session_released = False
        self._reset_localization_handshake()
        self._pending_package_generation = 0
        self._clear_prewarm_capture()
        self._active = False
        self._resident_material_signature = ""
        self._prewarm_package = None
        self._launch_is_prewarm = False
        if process is not None:
            stop_qprocess_async(process)
        self._retain_package_leases({self.desired_package_path})
        self._schedule_retry(reason, static_failure=static_failure)

    def _schedule_retry(self, reason: str, *, static_failure: bool) -> None:
        self._retry_reason = str(reason or ".NET/Vortice Preview is unavailable.")
        if self._desired_package is None and self._prewarm_package is not None:
            prewarm_path = str(self._prewarm_package.package_dir)
            self._prewarm_package = None
            self._launch_is_prewarm = False
            self._release_package_lease(prewarm_path)
        if self._closed or not self._visible or self._desired_package is None:
            self._set_state("inactive", self._retry_reason)
            return
        if static_failure:
            delay_ms = _STATIC_RETRY_DELAY_MS
        else:
            index = min(self._retry_attempt, len(_TRANSIENT_RETRY_DELAYS_MS))
            delay_ms = (
                _TRANSIENT_RETRY_DELAYS_MS[index]
                if index < len(_TRANSIENT_RETRY_DELAYS_MS)
                else _STEADY_RETRY_DELAY_MS
            )
            self._retry_attempt += 1
        self._retry_timer.start(delay_ms)
        self._set_state("retrying", f"{self._retry_reason} Retrying automatically.")

    def _required_protocol_capabilities(self) -> tuple[str, ...]:
        profile_capabilities = (
            _PREVIEW_PROTOCOL_CAPABILITIES
            if self.profile is DotNetPreviewProfile.PREVIEW
            else _AUTHORING_PROTOCOL_CAPABILITIES
        )
        direct = (
            ("direct_authoring_host_v1",)
            if self.profile is DotNetPreviewProfile.AUTHORING and self._direct_authoring
            else ()
        )
        return (*_BASE_PROTOCOL_CAPABILITIES, *profile_capabilities, *direct)

    def _send_json(self, payload: Mapping[str, object]) -> bool:
        process = self._process
        return process is not None and self._send_json_to_process(process, payload)

    @staticmethod
    def _send_json_to_process(process: object, payload: Mapping[str, object]) -> bool:
        if not qprocess_is_running(process):
            return False
        try:
            data = (
                json.dumps(
                    dict(payload),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                )
                + "\n"
            ).encode("utf-8")
            return int(process.write(data)) == len(data)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False

    def _can_send_protocol(self) -> bool:
        return self._process is not None and qprocess_is_running(self._process)

    def _safe_host_hwnd(self) -> int:
        try:
            return max(0, int(self._host_hwnd() or 0))
        except (RuntimeError, TypeError, ValueError):
            return 0

    def _event_process_matches(self, payload: Mapping[str, object]) -> bool:
        try:
            return int(payload.get("process_generation", 0) or 0) == self._process_generation
        except (TypeError, ValueError, OverflowError):
            return False

    def _package_event_is_current(self, payload: Mapping[str, object]) -> bool:
        try:
            request_id = int(payload.get("request_id", 0) or 0)
            generation = int(payload.get("generation", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return False
        return request_id == self._package_request_id and generation == self._package_generation

    def _is_current_process(self, process: object, generation: int) -> bool:
        return self._process is process and generation == self._process_generation

    @staticmethod
    def _delete_process_later(process: object) -> None:
        try:
            process.deleteLater()
        except (AttributeError, RuntimeError):
            pass

    @staticmethod
    def _package_key(package_dir: Path | str) -> str:
        try:
            return str(Path(package_dir).expanduser().resolve()).casefold()
        except OSError:
            return str(package_dir).casefold()

    @classmethod
    def _package_identity(
        cls,
        package: MeshDotNetExperimentPackage,
    ) -> tuple[str, str, str]:
        scene_signature = ""
        scene_path = getattr(package, "scene_manifest_path", None)
        if scene_path:
            try:
                scene_signature = hashlib.sha256(Path(scene_path).read_bytes()).hexdigest()
            except OSError:
                scene_signature = str(scene_path)
        return (
            cls._package_key(package.package_dir),
            str(getattr(package, "material_signature", "") or ""),
            scene_signature,
        )

    def _hold_package_lease(self, package_dir: Path) -> None:
        key = self._package_key(package_dir)
        if key in self._package_leases:
            return
        lease = acquire_dotnet_preview_package_cache_lease_for_path(Path(package_dir))
        if lease is not None:
            self._package_leases[key] = lease

    def _release_package_lease(self, package_dir: Path | str) -> None:
        lease = self._package_leases.pop(self._package_key(package_dir), None)
        release = getattr(lease, "release", None)
        if callable(release):
            release()

    def _retain_package_leases(self, package_paths: set[str]) -> None:
        keep = {self._package_key(path) for path in package_paths if path}
        for key, lease in tuple(self._package_leases.items()):
            if key in keep:
                continue
            self._package_leases.pop(key, None)
            release = getattr(lease, "release", None)
            if callable(release):
                release()

    def _release_package_leases(self) -> None:
        leases = tuple(self._package_leases.values())
        self._package_leases.clear()
        for lease in leases:
            release = getattr(lease, "release", None)
            if callable(release):
                release()

    def _set_state(self, state: str, message: str) -> None:
        self.state_changed.emit(str(state), str(message))


__all__ = ["DotNetPreviewSessionController"]
