"""Dedicated Rust Mesh Editor process protocol and shadow-session lifecycle."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping
from importlib import import_module
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QProcess, QProcessEnvironment, QThread, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from cdmw.constants import DEFAULT_UI_DATA_FONT_SIZE, DEFAULT_UI_FONT_SIZE
from cdmw.services.mesh_rust_contract import (
    RUST_MESH_EDIT_BACKEND,
    RUST_MESH_EDITOR_PROTOCOL,
    RUST_MESH_RENDERER,
    resolve_rust_mesh_editor,
    rust_mesh_editor_file_signature,
    validate_rust_mesh_editor_package,
)
from cdmw.ui.themes import get_theme
from cdmw.ui.mesh_editor.process_io import (
    DOTNET_PROTOCOL_BUFFER_LIMIT,
    DOTNET_PROTOCOL_EVENT_LIMIT,
    DOTNET_PROTOCOL_LINE_LIMIT,
    append_bounded_text,
    qprocess_is_running,
    register_owned_qprocess_for_exit,
    stop_qprocess_async,
    unregister_owned_qprocess_for_exit,
)

from cdmw.ui.mesh_editor.tab_rust_process import (
    MeshEditorRustProcessMixin,
    _rust_stderr_failure_marker,
    _rust_stderr_backtrace_start,
    _rust_stderr_backtrace_note,
    _RUST_PROTOCOL_QUEUE_LIMIT,
    _RUST_READY_TIMEOUT_MS,
    _RUST_FINISH_EXIT_TIMEOUT_MS,
    _RUST_DIAGNOSTIC_BUFFER_LIMIT,
    _RUST_DIAGNOSTIC_TEXT_LIMIT,
    _RUST_DIAGNOSTIC_LINE_LIMIT,
)


# Compatibility names retained for callers that inspect the retired preference.
# Production routing never reads or writes this setting and always uses Rust.
MESH_EDITOR_BACKEND_SETTING = "mesh_editor_backend"
MESH_EDITOR_BACKEND_VORTICE = "vortice"
MESH_EDITOR_BACKEND_RUST = "rust"








class MeshEditorRustEditorMixin(MeshEditorRustProcessMixin):
    def _initialize_rust_editor_runtime_state(self) -> None:
        # The legacy preference is deliberately ignored. Rust is the sole
        # production Mesh Editor and Archive Preview renderer. Compatibility
        # setting names are retained only as inert persisted inputs.
        self.mesh_editor_backend = MESH_EDITOR_BACKEND_RUST
        self.standalone_rust_prepare_thread: QThread | None = None
        self.standalone_rust_prepare_worker: object | None = None
        self.standalone_rust_prepare_request_id = 0
        self.standalone_rust_prepare_active_request_id = 0
        self.standalone_rust_prepare_controller: object | None = None
        self.standalone_rust_prepare_service: object | None = None
        self.standalone_rust_prepare_session_id = ""
        self.standalone_rust_prepare_process_generation = 0
        self.standalone_rust_protocol_thread: QThread | None = None
        self.standalone_rust_protocol_worker: object | None = None
        self.standalone_rust_protocol_request_id = 0
        self.standalone_rust_active_event: dict[str, object] | None = None
        self.standalone_rust_protocol_queue: list[dict[str, object]] = []
        self.standalone_rust_dispose_thread: QThread | None = None
        self.standalone_rust_dispose_worker: object | None = None
        self.standalone_rust_dispose_pending = False
        self.standalone_rust_dispose_active_session: object | None = None
        self.standalone_rust_dispose_active_root: Path | None = None
        self.standalone_rust_dispose_queue: list[tuple[object | None, Path]] = []
        self.standalone_rust_relaunch_request: dict[str, object] | None = None
        self.standalone_rust_process: QProcess | None = None
        self.standalone_rust_process_generation = 0
        self.standalone_rust_target_controller: object | None = None
        self.standalone_rust_authoring_session: object | None = None
        self.standalone_rust_owned_root = Path(tempfile.gettempdir()) / "cdmw-rust-mesh-editor"
        self.standalone_rust_session_root: Path | None = None
        self.standalone_rust_executable_path: Path | None = None
        self.standalone_rust_launch_executable_signature = ""
        self.standalone_rust_launch_parent_hwnd = 0
        self.standalone_rust_child_hwnd = 0
        self.standalone_rust_material_wait_session_id = ""
        self.standalone_rust_material_wait_controller: object | None = None
        self.standalone_rust_texture_unavailable_reason = ""
        self.standalone_rust_checked_executable = ""
        self.standalone_rust_checked_executable_signature = ""
        self.standalone_rust_incompatible_reason = ""
        self.standalone_rust_stdout_buffer = ""
        self.standalone_rust_stderr_tail = ""
        self.standalone_rust_stderr_diagnostic = ""
        self.standalone_rust_stderr_partial = ""
        self.standalone_rust_stderr_in_backtrace = False
        self.standalone_rust_protocol_events: list[dict[str, object]] = []
        self.standalone_rust_last_client_request_id = 0
        self.standalone_rust_host_request_id = 0
        self.standalone_rust_hello_received = False
        self.standalone_rust_ready = False
        self.standalone_rust_closing = False
        self.standalone_rust_finish_accepted = False
        self.standalone_rust_failure_reported = False
        self.standalone_rust_process_error_reported = False
        self.standalone_rust_stop_after_protocol = False
        self.standalone_rust_close_session_pending = False
        self.standalone_rust_terminal_close_pending = False
        self.standalone_rust_ready_timer = QTimer(self)
        self.standalone_rust_ready_timer.setSingleShot(True)
        self.standalone_rust_ready_timer.timeout.connect(self._handle_rust_ready_timeout)
        self.standalone_rust_finish_timer = QTimer(self)
        self.standalone_rust_finish_timer.setSingleShot(True)
        self.standalone_rust_finish_timer.timeout.connect(self._handle_rust_finish_exit_timeout)

    def _initialize_mesh_editor_backend_selector(self) -> None:
        self._sync_mesh_editor_backend_controls()

    def _selected_mesh_editor_backend(self) -> str:
        return MESH_EDITOR_BACKEND_RUST

    def _handle_mesh_editor_backend_changed(self, _index: int) -> None:
        self.mesh_editor_backend = MESH_EDITOR_BACKEND_RUST
        self._sync_mesh_editor_backend_controls()

    def _rust_executable_resolution(self) -> object:
        configured = str(
            self.settings.value("mesh_editor/rust_mesh_editor_executable", "") or ""
        ).strip()
        return resolve_rust_mesh_editor(configured)

    def _validate_rust_executable_resolution(
        self,
        resolution: object,
    ) -> tuple[str, str, str]:
        """Validate one stable executable/manifest pair and return its cache identity."""

        executable_text = str(getattr(resolution, "resolved_path", "") or "")
        signature_before = rust_mesh_editor_file_signature(resolution)
        reason = validate_rust_mesh_editor_package(resolution)
        signature_after = rust_mesh_editor_file_signature(resolution)
        if signature_before != signature_after:
            reason = "Rust executable package changed while it was being validated"
        return executable_text, signature_after, reason

    def _rust_open_preflight_reason(self) -> str:
        resolution = self._rust_executable_resolution()
        executable_text, executable_signature, reason = (
            self._validate_rust_executable_resolution(resolution)
        )
        self.standalone_rust_checked_executable = executable_text
        self.standalone_rust_checked_executable_signature = executable_signature
        self.standalone_rust_incompatible_reason = reason
        if reason:
            return reason
        if not bool(getattr(resolution, "is_file", False)) or not executable_text:
            return "the bundled editor was not found"
        return ""

    def _sync_mesh_editor_backend_controls(
        self,
        *,
        has_active_session: bool | None = None,
        task_active: bool | None = None,
    ) -> None:
        reason_label = getattr(self, "mesh_editor_backend_reason_label", None)
        open_button = getattr(self, "open_selected_mesh_button", None)
        if reason_label is None:
            return
        active = (
            bool(getattr(getattr(self, "standalone_controller", None), "active_session_id", ""))
            if has_active_session is None
            else bool(has_active_session)
        )
        busy = self._rust_editor_task_active() if task_active is None else bool(task_active)
        resolution = self._rust_executable_resolution()
        resolved_path = str(getattr(resolution, "resolved_path", "") or "")
        executable_signature = rust_mesh_editor_file_signature(resolution)
        if (
            resolved_path != self.standalone_rust_checked_executable
            or executable_signature != self.standalone_rust_checked_executable_signature
        ):
            (
                resolved_path,
                executable_signature,
                self.standalone_rust_incompatible_reason,
            ) = self._validate_rust_executable_resolution(resolution)
            self.standalone_rust_checked_executable = resolved_path
            self.standalone_rust_checked_executable_signature = executable_signature
        available = bool(getattr(resolution, "is_file", False))
        if self.standalone_rust_incompatible_reason:
            reason = f"Mesh Editor unavailable: {self.standalone_rust_incompatible_reason}"
            available = False
        elif available:
            reason = "Mesh Editor is ready."
        else:
            reason = "Mesh Editor unavailable: the bundled editor was not found."
        reason_label.setText(reason)
        reason_label.setToolTip(reason)
        if open_button is not None:
            target_getter = getattr(self, "_current_target_entry", None)
            has_target = (
                bool(target_getter())
                if callable(target_getter)
                else bool(open_button.isEnabled())
            )
            open_button.setEnabled(has_target and not active and not busy and available)
            open_button.setToolTip(
                "Open the selected archive mesh in the embedded Mesh Editor."
                if available
                else reason
            )

    def _rust_editor_task_active(self) -> bool:
        return bool(
            self.standalone_rust_prepare_thread is not None
            or self.standalone_rust_protocol_thread is not None
            or self.standalone_rust_dispose_thread is not None
            or self._rust_editor_process_running()
        )

    def _rust_editor_process_running(self) -> bool:
        return qprocess_is_running(getattr(self, "standalone_rust_process", None))

    def _rust_dispose_only_active(self) -> bool:
        return bool(
            self.standalone_rust_dispose_thread is not None
            and self.standalone_rust_prepare_thread is None
            and self.standalone_rust_protocol_thread is None
            and not self._rust_editor_process_running()
        )

    def _queue_rust_relaunch_after_dispose(self, controller: object) -> bool:
        """Retain one current-session Rust launch while old shadow cleanup finishes."""

        if not self._rust_dispose_only_active():
            return False
        current_controller = getattr(self, "standalone_controller", None)
        session_id = str(getattr(controller, "active_session_id", "") or "")
        if (
            controller is not current_controller
            or not session_id
            or self._selected_mesh_editor_backend() != MESH_EDITOR_BACKEND_RUST
        ):
            return False
        request = {
            "controller": controller,
            "session_id": session_id,
            "process_generation": int(self.standalone_rust_process_generation),
        }
        pending = self.standalone_rust_relaunch_request
        if not (
            isinstance(pending, Mapping)
            and pending.get("controller") is controller
            and pending.get("session_id") == session_id
            and pending.get("process_generation")
            == request["process_generation"]
        ):
            self.standalone_rust_relaunch_request = request
        self._set_rust_status("Mesh Editor is already starting or running.")
        return True

    def _cancel_rust_relaunch_after_dispose(self) -> None:
        self.standalone_rust_relaunch_request = None

    def _resume_rust_relaunch_after_dispose(self) -> None:
        request = self.standalone_rust_relaunch_request
        if not isinstance(request, Mapping):
            return
        # Consume first: every queued user request is attempted at most once.
        self.standalone_rust_relaunch_request = None
        controller = request.get("controller")
        current_controller = getattr(self, "standalone_controller", None)
        if (
            controller is None
            or controller is not current_controller
            or self._selected_mesh_editor_backend() != MESH_EDITOR_BACKEND_RUST
            or str(getattr(controller, "active_session_id", "") or "")
            != str(request.get("session_id", "") or "")
            or int(self.standalone_rust_process_generation)
            != int(request.get("process_generation", -1))
            or self._rust_editor_task_active()
        ):
            return
        self._start_selected_mesh_editor(controller)

    def _rust_finish_protocol_active(self) -> bool:
        return bool(
            self.standalone_rust_protocol_thread is not None
            and str(
                (self.standalone_rust_active_event or {}).get("event", "") or ""
            ).strip().lower()
            == "finish_request"
        )

    def _defer_standalone_close_for_rust_finish(self) -> bool:
        if self.standalone_rust_terminal_close_pending:
            # The protocol worker has already reached its terminal boundary,
            # but its UI-thread close is queued for the next event turn. Keep a
            # replacement open request behind that close so the queued callback
            # cannot tear down the new session after it starts.
            self.standalone_rust_close_session_pending = True
            return True
        if not self._rust_finish_protocol_active():
            return False
        self.standalone_rust_close_session_pending = True
        self._stop_rust_editor_process(
            reason="Cancelling Mesh Editor Finish before closing this mesh session..."
        )
        return True

    def _set_rust_status(self, message: str, *, error: bool = False) -> None:
        label = getattr(self, "standalone_status_label", None)
        if label is not None:
            label.setText(str(message or ""))
        self.status_message_requested.emit(str(message or ""), bool(error))

    def _start_selected_mesh_editor(self, controller: object) -> None:
        if self._defer_rust_editor_for_material_context(controller):
            return
        self._start_rust_editor_requested(controller)

    def _retry_rust_editor_requested(self) -> None:
        controller = getattr(self, "standalone_controller", None)
        if controller is None or not str(getattr(controller, "active_session_id", "") or ""):
            self._set_rust_status("Mesh Editor cannot retry because the mesh session is closed.", error=True)
            return
        host = getattr(self, "standalone_native_host_frame", None)
        show_loading = getattr(host, "show_loading", None)
        if callable(show_loading):
            show_loading("Rebuilding a fresh Mesh Editor shadow session...")
        self._start_selected_mesh_editor(controller)

    def _reopen_rust_editor_requested(self) -> None:
        controller = getattr(self, "standalone_controller", None)
        if controller is None or not str(getattr(controller, "active_session_id", "") or ""):
            self._set_rust_status("Mesh Editor cannot reopen because the accepted session is closed.", error=True)
            return
        host = getattr(self, "standalone_native_host_frame", None)
        show_loading = getattr(host, "show_loading", None)
        if callable(show_loading):
            show_loading("Reopening the accepted mesh revision for editing...")
        self._start_selected_mesh_editor(controller)

    def _defer_rust_editor_for_material_context(self, controller: object) -> bool:
        if bool(
            getattr(self, "archive_material_context_verified_for_rust", False)
        ):
            self.standalone_rust_texture_unavailable_reason = ""
            return False
        resolver = getattr(self, "_start_archive_material_context_resolution", None)
        if not callable(resolver) or not resolver():
            return False
        session_id = str(getattr(controller, "active_session_id", "") or "")
        if not session_id:
            return False
        self.standalone_rust_material_wait_session_id = session_id
        self.standalone_rust_material_wait_controller = controller
        self._set_rust_status(
            "Resolving this mesh's textures before Mesh Editor opens..."
        )
        return True

    def _resume_rust_editor_after_material_context(
        self,
        *,
        available: bool,
        reason: str = "",
    ) -> bool:
        expected_session_id = self.standalone_rust_material_wait_session_id
        if not expected_session_id:
            return False
        expected_controller = self.standalone_rust_material_wait_controller
        self.standalone_rust_material_wait_session_id = ""
        self.standalone_rust_material_wait_controller = None
        controller = getattr(self, "standalone_controller", None)
        current_session_id = str(
            getattr(controller, "active_session_id", "") or ""
        )
        if (
            controller is None
            or controller is not expected_controller
            or current_session_id != expected_session_id
        ):
            return True
        if not available and reason:
            authoring_module = import_module("cdmw.services.mesh_rust_authoring")
            concise = str(
                getattr(
                    authoring_module,
                    "concise_rust_texture_unavailable_reason",
                )(reason)
                or ""
            ).strip()
            self.standalone_rust_texture_unavailable_reason = concise
            self._set_rust_status(
                "Mesh Editor is checking matching archive DDS textures while "
                f"its shadow session opens: {concise}",
            )
        elif available:
            self.standalone_rust_texture_unavailable_reason = ""
        self._start_rust_editor_requested(controller)
        return True

    def _cancel_rust_material_context_wait(self) -> None:
        self.standalone_rust_material_wait_session_id = ""
        self.standalone_rust_material_wait_controller = None

    def _rust_theme_payload(self) -> dict[str, object]:
        application = QApplication.instance()
        font = application.font() if application is not None else self.font()
        screen = application.primaryScreen() if application is not None else None
        theme_key = str(getattr(self, "theme_key", "graphite") or "graphite")
        palette = {
            str(key): str(value)
            for key, value in get_theme(theme_key).items()
            if key != "label"
        }
        window_colour = QColor(palette.get("window", "#1e1e1e"))
        font_point_size = float(font.pointSizeF())
        if font_point_size <= 0.0:
            font_point_size = float(DEFAULT_UI_FONT_SIZE)
        try:
            data_font_point_size = float(
                self.settings.value(
                    "appearance/data_font_size",
                    DEFAULT_UI_DATA_FONT_SIZE,
                )
            )
        except (TypeError, ValueError):
            data_font_point_size = float(DEFAULT_UI_DATA_FONT_SIZE)
        return {
            "schema": "cdmw_ui_theme_v1",
            "theme": theme_key,
            "variant": "dark" if window_colour.lightnessF() < 0.5 else "light",
            "palette": palette,
            "font_family": font.family(),
            "font_point_size": font_point_size,
            "data_font_point_size": data_font_point_size,
            "density": str(self.settings.value("appearance/ui_density", "compact") or "compact"),
            "scale": float(screen.devicePixelRatio()) if screen is not None else 1.0,
        }

    def _send_rust_theme_update(self) -> bool:
        """Apply an app appearance change to the already embedded child."""

        if not self.standalone_rust_ready:
            return False
        self.standalone_rust_host_request_id += 1
        return self._send_rust_message(
            self._rust_host_message(
                "theme_update",
                request_id=self.standalone_rust_host_request_id,
                extra={"payload": self._rust_theme_payload()},
            )
        )

    def _prime_rust_preview_material_context(self, controller: object) -> int:
        preview_model = getattr(
            self,
            "standalone_archive_material_preview_model",
            None,
        )
        prime = getattr(
            import_module("cdmw.services.mesh_rust_authoring"),
            "prime_rust_mesh_preview_context",
        )
        archive_texture_indexes = getattr(self, "_archive_texture_indexes", None)
        try:
            _path_index, basename_index = (
                archive_texture_indexes()
                if callable(archive_texture_indexes)
                else ({}, {})
            )
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            basename_index = {}
        current_target = getattr(self, "_current_target_entry", None)
        target_entry = (
            current_target()
            if callable(current_target)
            else getattr(self, "current_archive_selection", None)
        )
        return int(
            prime(
                controller,
                preview_model,
                material_package_path=getattr(
                    self,
                    "archive_material_context_package_path",
                    "",
                ),
                unavailable_reason=self.standalone_rust_texture_unavailable_reason,
                target_entry=target_entry,
                entries_by_basename=basename_index,
            )
        )

    def _start_rust_editor_requested(self, controller: object) -> None:
        if self._rust_editor_task_active():
            if self._queue_rust_relaunch_after_dispose(controller):
                return
            self._set_rust_status("Mesh Editor is already starting or running.")
            return
        resolution = self._rust_executable_resolution()
        (
            executable_text,
            executable_signature,
            incompatibility_reason,
        ) = self._validate_rust_executable_resolution(resolution)
        self.standalone_rust_checked_executable = executable_text
        self.standalone_rust_checked_executable_signature = executable_signature
        self.standalone_rust_incompatible_reason = incompatibility_reason
        if (
            not bool(getattr(resolution, "is_file", False))
            or not executable_text
            or incompatibility_reason
        ):
            reason = incompatibility_reason or "cdmw_mesh_lab.exe was not found"
            self._set_rust_status(f"Mesh Editor unavailable: {reason}.", error=True)
            self._sync_mesh_editor_backend_controls()
            return
        try:
            self._prime_rust_preview_material_context(controller)
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self._set_rust_status(
                f"Mesh Editor could not bind the resolved preview textures: {exc}",
                error=True,
            )
            self._sync_mesh_editor_backend_controls()
            return
        self.standalone_rust_process_generation += 1
        self.standalone_rust_prepare_request_id += 1
        expected_session_id = str(
            getattr(controller, "active_session_id", "") or ""
        )
        expected_service = getattr(controller, "mesh_service", None)
        if (
            controller is not getattr(self, "standalone_controller", None)
            or not expected_session_id
            or expected_service is None
        ):
            self._set_rust_status(
                "Mesh Editor could not start because the selected mesh session changed.",
                error=True,
            )
            self._sync_mesh_editor_backend_controls()
            return
        self.standalone_rust_target_controller = controller
        self.standalone_rust_executable_path = Path(executable_text)
        self.standalone_rust_launch_executable_signature = executable_signature
        self.standalone_rust_session_root = self.standalone_rust_owned_root / f"session-{uuid4().hex}"
        host = getattr(self, "standalone_native_host_frame", None)
        show_loading = getattr(host, "show_loading", None)
        if callable(show_loading):
            show_loading("Preparing the embedded Mesh Editor...")
        self._reset_rust_protocol_state()
        request_id = self.standalone_rust_prepare_request_id
        process_generation = self.standalone_rust_process_generation
        self.standalone_rust_prepare_active_request_id = request_id
        self.standalone_rust_prepare_controller = controller
        self.standalone_rust_prepare_service = expected_service
        self.standalone_rust_prepare_session_id = expected_session_id
        self.standalone_rust_prepare_process_generation = process_generation
        worker_type = getattr(
            import_module("cdmw.workers.mesh_rust_editor_workers"),
            "MeshRustSessionPrepareWorker",
        )
        worker = worker_type(
            request_id,
            controller,
            self.standalone_rust_session_root,
            process_generation=process_generation,
            theme=self._rust_theme_payload(),
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.prepared.connect(self._handle_rust_session_prepared)
        worker.error.connect(self._handle_rust_session_prepare_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(
            lambda current=thread: self._handle_rust_prepare_thread_finished(current)
        )
        thread.finished.connect(thread.deleteLater)
        self.standalone_rust_prepare_worker = worker
        self.standalone_rust_prepare_thread = thread
        self._set_rust_status("Preparing an isolated Mesh Editor session...")
        self._sync_mesh_editor_backend_controls(task_active=True)
        if not self._rust_prepare_context_is_current(
            request_id=request_id,
            controller=controller,
            service=expected_service,
            session_id=expected_session_id,
            process_generation=process_generation,
        ):
            self._stop_rust_session_prepare(invalidate=True)
            self.standalone_rust_prepare_worker = None
            self.standalone_rust_prepare_thread = None
            worker.deleteLater()
            thread.deleteLater()
            self._reset_rust_session_references()
            self._set_rust_status(
                "Mesh Editor preparation was cancelled because the mesh session changed.",
                error=True,
            )
            self._sync_mesh_editor_backend_controls()
            return
        thread.start()

    def _rust_prepare_context_is_current(
        self,
        *,
        request_id: int,
        controller: object,
        service: object,
        session_id: str,
        process_generation: int,
    ) -> bool:
        current_controller = getattr(self, "standalone_controller", None)
        return bool(
            request_id == self.standalone_rust_prepare_request_id
            and request_id == self.standalone_rust_prepare_active_request_id
            and controller is self.standalone_rust_prepare_controller
            and controller is self.standalone_rust_target_controller
            and controller is current_controller
            and service is self.standalone_rust_prepare_service
            and service is getattr(current_controller, "mesh_service", None)
            and str(getattr(current_controller, "active_session_id", "") or "")
            == session_id
            and session_id == self.standalone_rust_prepare_session_id
            and process_generation == self.standalone_rust_process_generation
            and process_generation
            == self.standalone_rust_prepare_process_generation
            and not self.standalone_rust_closing
        )

    def _stop_rust_session_prepare(self, *, invalidate: bool) -> None:
        active_request_id = self.standalone_rust_prepare_active_request_id
        worker = self.standalone_rust_prepare_worker
        if worker is not None and (not invalidate or active_request_id):
            stop = getattr(worker, "stop", None)
            if callable(stop):
                try:
                    stop()
                except RuntimeError:
                    pass
        if not invalidate:
            return
        if active_request_id:
            if self.standalone_rust_prepare_request_id == active_request_id:
                self.standalone_rust_prepare_request_id += 1
            self.standalone_rust_prepare_active_request_id = 0
        self.standalone_rust_prepare_controller = None
        self.standalone_rust_prepare_service = None
        self.standalone_rust_prepare_session_id = ""
        self.standalone_rust_prepare_process_generation = 0

    def _reset_rust_protocol_state(self) -> None:
        self.standalone_rust_protocol_queue.clear()
        self.standalone_rust_protocol_events.clear()
        self.standalone_rust_stdout_buffer = ""
        self.standalone_rust_stderr_tail = ""
        self.standalone_rust_stderr_diagnostic = ""
        self.standalone_rust_stderr_partial = ""
        self.standalone_rust_stderr_in_backtrace = False
        self.standalone_rust_last_client_request_id = 0
        self.standalone_rust_host_request_id = 0
        self.standalone_rust_hello_received = False
        self.standalone_rust_ready = False
        self.standalone_rust_closing = False
        self.standalone_rust_finish_accepted = False
        self.standalone_rust_failure_reported = False
        self.standalone_rust_process_error_reported = False
        self.standalone_rust_stop_after_protocol = False
        self.standalone_rust_ready_timer.stop()
        self.standalone_rust_finish_timer.stop()

    def _handle_rust_session_prepared(
        self,
        request_id: int,
        session: object,
    ) -> None:
        controller = self.standalone_rust_prepare_controller
        service = self.standalone_rust_prepare_service
        session_id = self.standalone_rust_prepare_session_id
        process_generation = self.standalone_rust_prepare_process_generation
        context_is_current = bool(
            controller is not None
            and service is not None
            and self._rust_prepare_context_is_current(
                request_id=request_id,
                controller=controller,
                service=service,
                session_id=session_id,
                process_generation=process_generation,
            )
            and str(getattr(session, "authoritative_session_id", "") or "")
            == session_id
            and getattr(session, "authoritative_service", None) is service
            and int(getattr(session, "process_generation", 0) or 0)
            == process_generation
        )
        if not context_is_current:
            if request_id == self.standalone_rust_prepare_active_request_id:
                self._stop_rust_session_prepare(invalidate=True)
            self._start_rust_dispose_worker(session, session.root)
            return
        self.standalone_rust_prepare_active_request_id = 0
        self.standalone_rust_prepare_controller = None
        self.standalone_rust_prepare_service = None
        self.standalone_rust_prepare_session_id = ""
        self.standalone_rust_prepare_process_generation = 0
        self.standalone_rust_authoring_session = session
        self.standalone_rust_session_root = session.root
        self.standalone_rust_texture_unavailable_reason = str(
            getattr(session, "texture_unavailable_reason", "") or ""
        ).strip()
        self._launch_rust_editor_process(session)

    def _handle_rust_session_prepare_error(self, request_id: int, message: str) -> None:
        if request_id != self.standalone_rust_prepare_request_id:
            return
        self._stop_rust_session_prepare(invalidate=True)
        self._set_rust_status(f"Mesh Editor could not prepare its shadow session: {message}", error=True)
        self.standalone_rust_target_controller = None
        self.standalone_rust_dispose_pending = True

    def _handle_rust_prepare_thread_finished(self, thread: QThread) -> None:
        if self.standalone_rust_prepare_thread is not thread:
            return
        abandoned_prepare = bool(self.standalone_rust_prepare_active_request_id)
        self.standalone_rust_prepare_thread = None
        self.standalone_rust_prepare_worker = None
        if abandoned_prepare:
            self._stop_rust_session_prepare(invalidate=True)
            self._reset_rust_session_references()
            self._set_rust_status(
                "Mesh Editor preparation was cancelled because the mesh session changed.",
                error=True,
            )
        if self.standalone_rust_dispose_pending and self.standalone_rust_process is None:
            self._schedule_rust_session_dispose()
        self._sync_mesh_editor_backend_controls()


    def _schedule_rust_session_dispose(self) -> None:
        self._stop_rust_session_prepare(invalidate=True)
        if (
            self.standalone_rust_process is not None
            or self.standalone_rust_protocol_thread is not None
            or self.standalone_rust_prepare_thread is not None
        ):
            self.standalone_rust_dispose_pending = True
            return
        session = self.standalone_rust_authoring_session
        root = self.standalone_rust_session_root
        if root is None:
            if (
                self.standalone_rust_dispose_thread is None
                and not self.standalone_rust_dispose_queue
            ):
                self._reset_rust_session_references()
            return
        self._start_rust_dispose_worker(session, root)

    def _rust_dispose_request_is_known(
        self,
        session: object | None,
        root: Path,
    ) -> bool:
        if (
            self.standalone_rust_dispose_thread is not None
            and self.standalone_rust_dispose_active_session is session
            and self.standalone_rust_dispose_active_root == root
        ):
            return True
        return any(
            queued_session is session and queued_root == root
            for queued_session, queued_root in self.standalone_rust_dispose_queue
        )

    def _start_rust_dispose_worker(
        self,
        session: object | None,
        root: Path,
    ) -> None:
        root = Path(root)
        if self.standalone_rust_dispose_thread is not None:
            if not self._rust_dispose_request_is_known(session, root):
                self.standalone_rust_dispose_queue.append((session, root))
            self.standalone_rust_dispose_pending = bool(
                self.standalone_rust_dispose_queue
            )
            return
        worker_type = getattr(
            import_module("cdmw.workers.mesh_rust_editor_workers"),
            "MeshRustSessionDisposeWorker",
        )
        worker = worker_type(session, root, self.standalone_rust_owned_root)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.error.connect(
            lambda message: self._set_rust_status(
                f"Mesh Editor cleanup warning: {message}",
                error=True,
            )
        )
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(
            lambda current=thread: self._handle_rust_dispose_thread_finished(current)
        )
        thread.finished.connect(thread.deleteLater)
        self.standalone_rust_dispose_pending = bool(self.standalone_rust_dispose_queue)
        self.standalone_rust_dispose_active_session = session
        self.standalone_rust_dispose_active_root = root
        self.standalone_rust_dispose_worker = worker
        self.standalone_rust_dispose_thread = thread
        thread.start()

    def _handle_rust_dispose_thread_finished(self, thread: QThread) -> None:
        if self.standalone_rust_dispose_thread is not thread:
            return
        disposed_session = self.standalone_rust_dispose_active_session
        disposed_root = self.standalone_rust_dispose_active_root
        self.standalone_rust_dispose_thread = None
        self.standalone_rust_dispose_worker = None
        self.standalone_rust_dispose_active_session = None
        self.standalone_rust_dispose_active_root = None
        current_root = self.standalone_rust_session_root
        if (
            disposed_root is not None
            and self.standalone_rust_authoring_session is disposed_session
            and current_root is not None
            and Path(current_root) == disposed_root
        ):
            self._reset_rust_session_references()
        if self.standalone_rust_dispose_queue:
            queued_session, queued_root = self.standalone_rust_dispose_queue.pop(0)
            self.standalone_rust_dispose_pending = bool(
                self.standalone_rust_dispose_queue
            )
            self._start_rust_dispose_worker(queued_session, queued_root)
        else:
            self.standalone_rust_dispose_pending = False
        self._sync_mesh_editor_backend_controls()
        if (
            self.standalone_rust_dispose_thread is None
            and not self.standalone_rust_dispose_queue
        ):
            self._resume_rust_relaunch_after_dispose()

    def _reset_rust_session_references(self) -> None:
        self._stop_rust_session_prepare(invalidate=True)
        self.standalone_rust_authoring_session = None
        self.standalone_rust_target_controller = None
        self.standalone_rust_session_root = None
        self.standalone_rust_executable_path = None
        self.standalone_rust_launch_executable_signature = ""
        self.standalone_rust_launch_parent_hwnd = 0
        self.standalone_rust_child_hwnd = 0
        self.standalone_rust_texture_unavailable_reason = ""
        self.standalone_rust_dispose_pending = False
        self.standalone_rust_closing = False
        self.standalone_rust_close_session_pending = False
        self.standalone_rust_terminal_close_pending = False


__all__ = [
    "MESH_EDITOR_BACKEND_RUST",
    "MESH_EDITOR_BACKEND_SETTING",
    "MESH_EDITOR_BACKEND_VORTICE",
    "MeshEditorRustEditorMixin",
]
