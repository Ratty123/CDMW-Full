"""Runtime loop for native D3D11 archive preview processes."""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import List, Mapping, Sequence

from PySide6.QtCore import QProcess, QTimer

from cdmw.models import ArchivePreviewResult
from cdmw.ui.shell.diagnostics_controller import d3d11_status_file_signature as _d3d11_status_file_signature


_ARCHIVE_OVERHEAD_CAMERA_SEGMENTS = frozenset(
    {
        "weapon",
        "subweapon",
        "shield",
        "onehandweapon",
        "twohandweapon",
        "sword",
        "longsword",
        "greatsword",
        "dagger",
        "axe",
        "spear",
        "lance",
        "staff",
        "mace",
        "hammer",
        "bow",
        "crossbow",
        "musket",
        "cannon",
        "instrument",
    }
)


def _archive_model_uses_overhead_camera(source_path: object) -> bool:
    normalized = str(source_path or "").replace("\\", "/").strip().casefold()
    if not normalized:
        return False
    segments = tuple(segment for segment in normalized.split("/") if segment)
    for segment in segments[:-1] if len(segments) > 1 else segments:
        family = segment.lstrip("0123456789_-")
        if family in _ARCHIVE_OVERHEAD_CAMERA_SEGMENTS:
            return True
    return False


def _archive_model_manifest_source_path(package_dir: Path) -> str:
    try:
        payload = json.loads((Path(package_dir) / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ""
    if not isinstance(payload, Mapping):
        return ""
    return str(payload.get("source_path", "") or "").strip()


def archive_model_initial_view_state(source_path: object = "") -> dict[str, object]:
    """Return the fitted camera chosen from a newly selected archive model path."""

    overhead = _archive_model_uses_overhead_camera(source_path)

    return {
        "role": "replacement",
        "reason": "archive_model_initial_overhead" if overhead else "archive_model_initial_front",
        "zoom_factor": 1.0,
        "fit_to_view": True,
        "yaw": 0.0,
        "pitch": -89.0 if overhead else 0.0,
        "pan": (0.0, 0.0, 0.0),
    }


def _archive_status_reports_device_loss(payload: Mapping[str, object]) -> bool:
    reason = str(payload.get("reason", "") or "").strip().lower()
    event = str(payload.get("event", "") or "").strip().lower()
    return bool(payload.get("device_lost", False)) or reason == "device_lost" or event == "device_lost"


class ArchivePreviewD3D11RuntimeMixin:
    """Start, poll, and shut down native D3D11 preview processes."""

    def _restore_archive_d3d11_pending_view_state(self) -> bool:
        state = getattr(self, "archive_d3d11_pending_view_state", {})
        if not isinstance(state, Mapping) or not state:
            return False
        if not self.archive_d3d11_preview_host.restore_view_state(state):
            return False
        self.archive_d3d11_pending_view_state = {}
        return True

    def _record_archive_d3d11_runtime_event(self, event: str, **fields: object) -> None:
        recorder = getattr(self, "_record_runtime_event", None)
        if callable(recorder):
            recorder(event, **fields)

    def _set_archive_d3d11_last_active_operation(self, operation: str, **fields: object) -> None:
        setter = getattr(self, "_set_last_active_operation", None)
        if callable(setter):
            setter(operation, **fields)

    def _configure_archive_isolated_renderer_process(
        self,
        process: QProcess,
        status_file: Path,
    ) -> int:
        try:
            process.setWorkingDirectory(str(Path(__file__).resolve().parents[3]))
        except Exception:
            pass
        process.setProcessChannelMode(QProcess.SeparateChannels)
        generation = self._register_archive_isolated_renderer_process(process, status_file)
        process.started.connect(lambda: self.set_status_message("Starting isolated D3D11 renderer..."))
        process.readyReadStandardError.connect(
            partial(self._handle_archive_isolated_renderer_stderr, process, generation)
        )
        process.finished.connect(
            partial(self._handle_archive_isolated_renderer_finished, process, generation)
        )
        process.errorOccurred.connect(
            partial(self._handle_archive_isolated_renderer_error, process, generation)
        )
        track_process = getattr(self.archive_d3d11_preview_host, "track_renderer_process", None)
        if callable(track_process):
            track_process(process)
        return generation

    def _start_archive_isolated_renderer_process(self, package_dir: Path) -> None:
        valid_package, missing_paths = self._validate_d3d11_preview_package_paths(package_dir)
        if not valid_package:
            message = "Native D3D11 package validation failed: " + "; ".join(missing_paths[:6])
            self._record_archive_d3d11_runtime_event(
                "d3d11_renderer_start_blocked_invalid_package",
                package_dir=str(package_dir),
                missing=list(missing_paths[:12]),
            )
            self.set_status_message(message, error=True)
            self.archive_d3d11_preview_status_label.setText("D3D11 package validation failed.")
            self._set_archive_isolated_renderer_debug(message)
            self._clear_archive_d3d11_part_visibility_menu()
            return
        self._populate_archive_d3d11_part_visibility_menu(package_dir)
        status_file = package_dir / "host_status.json"
        self._set_archive_d3d11_last_active_operation(
            "d3d11_renderer_start",
            package_dir=str(package_dir),
            status_file=str(status_file),
            request_id=self.archive_preview_request_id,
        )
        try:
            status_file.unlink(missing_ok=True)
        except OSError:
            pass
        next_model_key = self._d3d11_preview_package_model_key(package_dir)
        active_model_key = str(getattr(self, "archive_d3d11_active_model_key", "") or "").strip()
        same_d3d11_model = bool(next_model_key and active_model_key and next_model_key == active_model_key)
        view_state_for_load = (
            self._sanitize_d3d11_view_state_for_restore(self.archive_d3d11_view_state)
            if same_d3d11_model and bool(getattr(self, "archive_d3d11_has_view_state", False))
            else archive_model_initial_view_state(_archive_model_manifest_source_path(package_dir))
        )
        if same_d3d11_model and view_state_for_load and bool(view_state_for_load.get("fit_to_view", True)):
            # Same model refresh: keep camera feel while allowing the package to refit its center.
            view_state_for_load["pan"] = (0.0, 0.0, 0.0)
            view_state_for_load["zoom_factor"] = 1.0
            view_state_for_load["fit_to_view"] = True
        if not same_d3d11_model:
            self.archive_d3d11_view_state = {}
            self.archive_d3d11_has_view_state = False
        self.archive_d3d11_pending_view_state = dict(view_state_for_load)
        self.archive_isolated_renderer_status_file = status_file
        self.archive_isolated_renderer_status_signature = (0, 0)
        self.archive_isolated_renderer_status_payload_text = ""
        self.archive_isolated_renderer_last_status_payload = {}
        if self._archive_isolated_renderer_process_running():
            active_process = getattr(self, "archive_isolated_renderer_process", None)
            if active_process is not None:
                self._set_archive_isolated_renderer_process_status_file(active_process, status_file)
            source = str(getattr(self, "archive_isolated_renderer_pending_package_source", "") or "")
            self._set_archive_d3d11_pending_package(
                package_dir,
                status_file,
                source or self.archive_isolated_renderer_package_source,
                next_model_key,
            )
            self._record_archive_d3d11_runtime_event(
                "d3d11_renderer_reload",
                package_dir=str(package_dir),
                status_file=str(status_file),
                same_model=same_d3d11_model,
                process_pid=self._archive_qprocess_pid(getattr(self, "archive_isolated_renderer_process", None)),
            )
            self.archive_preview_stack.setCurrentWidget(self.archive_d3d11_preview_host)
            self.archive_d3d11_preview_status_label.setText("Reloading native D3D11 preview...")
            self._set_archive_isolated_renderer_debug(
                "Native D3D11 Preview: loading the next package while the current preview remains visible."
            )
            self.archive_isolated_renderer_status_timer.start()
            if self.archive_d3d11_preview_host.load_package(
                package_dir,
                status_file,
                reset_view=not same_d3d11_model,
            ):
                self.archive_d3d11_preview_host.set_render_tuning(self._current_model_preview_render_settings())
                QTimer.singleShot(0, self._restore_archive_d3d11_pending_view_state)
                QTimer.singleShot(
                    10000,
                    lambda expected_status=status_file: self._check_archive_isolated_renderer_start_timeout(expected_status),
                )
                return
            self.archive_isolated_renderer_pending_package = None
            self.archive_isolated_renderer_pending_status_file = None
            self.archive_isolated_renderer_pending_package_source = ""
            self.archive_d3d11_pending_model_key = ""
            process = getattr(self, "archive_isolated_renderer_process", None)
            if process is not None:
                generation = self._archive_isolated_renderer_generation_for_process(process)
                try:
                    process.finished.connect(lambda *_args, process=process: self._delete_archive_qprocess_later(process))
                except (RuntimeError, TypeError):
                    pass
                self._kill_archive_isolated_renderer_process_if_running(
                    process,
                    generation=generation,
                    reason="reload_fallback",
                )
        previous = getattr(self, "archive_isolated_renderer_active_package", None)
        if previous is None or Path(previous) != Path(package_dir):
            if previous is not None:
                self.archive_isolated_renderer_retired_packages.append(previous)
            self.archive_isolated_renderer_active_package = package_dir
        self.archive_d3d11_active_model_key = next_model_key
        pending_source = str(getattr(self, "archive_isolated_renderer_pending_package_source", "") or "").strip()
        if pending_source:
            self.archive_isolated_renderer_package_source = pending_source
            self.archive_isolated_renderer_pending_package_source = ""
            self.archive_d3d11_pending_model_key = ""
        process = QProcess(self)
        try:
            program, arguments = self._archive_isolated_renderer_command(package_dir, status_file)
        except Exception as exc:
            self._record_archive_d3d11_runtime_event(
                "d3d11_renderer_command_unavailable",
                package_dir=str(package_dir),
                message=str(exc),
            )
            self.set_status_message(f"Native D3D11 renderer is unavailable: {exc}", error=True)
            self._set_archive_isolated_renderer_debug(
                f"Isolated Renderer: native D3D11 host unavailable: {exc}\n"
                "Build native/cdmw_d3d11_preview or set CDMW_D3D11_PREVIEW_BIN. "
                "Defender note: if Windows Defender quarantines an unsigned experimental EXE, submit it to Microsoft for analysis before allowing it: "
                "https://www.microsoft.com/wdsi/filesubmission"
            )
            self._cleanup_archive_isolated_renderer_packages(include_active=True)
            self._show_archive_d3d11_hard_failure(f"Native D3D11 renderer is unavailable: {exc}")
            return
        process.setProgram(program)
        process.setArguments(arguments)
        self._record_archive_d3d11_runtime_event(
            "d3d11_renderer_process_configured",
            program=program,
            arguments=arguments,
            package_dir=str(package_dir),
            status_file=str(status_file),
        )
        self._configure_archive_isolated_renderer_process(process, status_file)
        self.archive_isolated_renderer_process = process
        self.archive_isolated_renderer_active_process = process
        self.archive_preview_stack.setCurrentWidget(self.archive_d3d11_preview_host)
        self.archive_d3d11_preview_status_label.setText("Loading preview... starting renderer.")
        self._set_archive_isolated_renderer_debug(
            "Native D3D11 Preview: launching embedded one-shot preview. "
            f"Package: {package_dir}\n"
            "If Windows Defender quarantines this unsigned experimental build, submit the EXE to Microsoft for analysis before allowing it: "
            "https://www.microsoft.com/wdsi/filesubmission"
        )
        self.archive_isolated_renderer_status_timer.start()
        process.start()
        QTimer.singleShot(10000, lambda expected_status=status_file: self._check_archive_isolated_renderer_start_timeout(expected_status))

    def _check_archive_isolated_renderer_start_timeout(self, expected_status: Path) -> None:
        if getattr(self, "archive_isolated_renderer_status_file", None) != expected_status:
            return
        if not self._archive_isolated_renderer_process_running():
            return
        if expected_status.is_file():
            return
        self.set_status_message("Isolated D3D11 renderer has not written a status file yet.", error=True)
        self._record_archive_d3d11_runtime_event(
            "d3d11_renderer_start_timeout",
            status_file=str(expected_status),
            process_pid=self._archive_qprocess_pid(getattr(self, "archive_isolated_renderer_process", None)),
        )
        self._set_archive_isolated_renderer_debug(
            "Isolated Renderer: startup timeout waiting for status file. "
            "If Windows Defender quarantines the unsigned EXE, submit it to Microsoft before allowing it: "
            "https://www.microsoft.com/wdsi/filesubmission"
        )
        process = getattr(self, "archive_isolated_renderer_process", None)
        if process is not None:
            generation = self._archive_isolated_renderer_generation_for_process(process)
            try:
                process.finished.connect(lambda *_args, process=process: self._delete_archive_qprocess_later(process))
            except (RuntimeError, TypeError):
                pass
            self._kill_archive_isolated_renderer_process_if_running(
                process,
                generation=generation,
                reason="startup_timeout",
            )
        had_pending = self._discard_archive_d3d11_pending_package(expected_status)
        self.archive_isolated_renderer_process = None
        self.archive_isolated_renderer_active_process = None
        self.archive_isolated_renderer_status_timer.stop()
        self._cleanup_archive_isolated_renderer_packages(include_active=not had_pending)
        self._show_archive_d3d11_hard_failure("Isolated D3D11 renderer did not start in time.")

    def _open_archive_isolated_d3d11_preview(self) -> None:
        result = self.current_archive_preview_result
        if result is None or self.archive_preview_showing_loose or getattr(result, "preview_model", None) is None:
            self.set_status_message("Select an archive model preview before reloading the selected renderer.", error=True)
            return
        self._launch_archive_isolated_preview_result(result)

    def _sync_archive_isolated_renderer_if_running(self, result: ArchivePreviewResult) -> None:
        del result
        return

    def _handle_archive_isolated_renderer_stderr(self, process: QProcess, generation: int) -> None:
        if not self._archive_isolated_renderer_signal_is_current(process, generation):
            return
        try:
            chunk = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        except RuntimeError:
            return
        if chunk:
            self._record_archive_d3d11_runtime_event("d3d11_renderer_stderr", message=chunk[-1200:])
            self._set_archive_isolated_renderer_debug(f"Isolated Renderer stderr: {chunk[-1200:]}")

    def _poll_archive_isolated_renderer_status(self) -> None:
        status_file = getattr(self, "archive_isolated_renderer_status_file", None)
        if status_file is None:
            return
        try:
            stat = status_file.stat()
        except OSError:
            if str(getattr(self.archive_d3d11_preview_status_label, "text", lambda: "")()).strip() and self.archive_d3d11_preview_host.isVisible():
                self.archive_d3d11_preview_status_label.setText("")
            return
        signature = _d3d11_status_file_signature(stat)
        try:
            payload_text = status_file.read_text(encoding="utf-8")
        except Exception as exc:
            self._set_archive_isolated_renderer_debug(f"Isolated Renderer: status read failed: {exc}")
            return
        if (
            signature == getattr(self, "archive_isolated_renderer_status_signature", (0, 0))
            and payload_text == getattr(self, "archive_isolated_renderer_status_payload_text", "")
        ):
            last_event = str((getattr(self, "archive_isolated_renderer_last_status_payload", {}) or {}).get("event", "") or "").strip().lower()
            if last_event == "loaded":
                self.archive_d3d11_preview_status_label.setText("")
            return
        self.archive_isolated_renderer_status_signature = signature
        self.archive_isolated_renderer_status_payload_text = payload_text
        try:
            payload = json.loads(payload_text)
        except Exception as exc:
            self._set_archive_isolated_renderer_debug(f"Isolated Renderer: status read failed: {exc}")
            return
        if not isinstance(payload, Mapping):
            return
        self.archive_isolated_renderer_last_status_payload = dict(payload)
        event = str(payload.get("event", "") or "").strip().lower()
        self._record_archive_d3d11_runtime_event(
            "d3d11_status_event",
            status_event=event,
            status_file=str(status_file),
            stage=payload.get("stage", ""),
            message=payload.get("message", ""),
            batch_count=payload.get("batch_count", 0),
            vertex_count=payload.get("vertex_count", 0),
            texture_cache_entries=payload.get("texture_cache_entries", 0),
            texture_cache_releases=payload.get("texture_cache_releases", 0),
            texture_failures=payload.get("texture_failures", 0),
            texture_integrity=payload.get("texture_integrity", ""),
            device_lost=payload.get("device_lost", False),
            device_loss_stage=payload.get("device_loss_stage", payload.get("stage", "")),
            device_loss_hresult=payload.get("device_loss_hresult", ""),
            device_removed_reason=payload.get("device_removed_reason", ""),
            estimated_texture_bytes=payload.get("estimated_texture_bytes", 0),
            d3d11_process_working_set_bytes=payload.get("process_working_set_bytes", 0),
            d3d11_process_private_bytes=payload.get("process_private_bytes", 0),
            frame_count=payload.get("frame_count", 0),
            render_request_count=payload.get("render_request_count", 0),
            render_suppressed_count=payload.get("render_suppressed_count", 0),
            parent_unresponsive_count=payload.get("parent_unresponsive_count", 0),
            parent_health=payload.get("parent_health", ""),
            process_pid=self._archive_qprocess_pid(getattr(self, "archive_isolated_renderer_process", None)),
        )
        if event == "loaded":
            self._promote_archive_d3d11_pending_package_if_loaded(status_file)
            self._restore_archive_d3d11_pending_view_state()
            self.archive_d3d11_preview_host.set_render_tuning(self._current_model_preview_render_settings())
            self._set_archive_d3d11_hidden_parts_from_menu()
            self._cleanup_archive_isolated_renderer_packages(include_active=False)
            self._set_archive_isolated_renderer_debug(self._format_archive_isolated_renderer_debug(payload))
            texture_integrity = str(payload.get("texture_integrity", "ok") or "ok").strip().lower()
            if texture_integrity and texture_integrity != "ok":
                message = f"D3D11 preview loaded with texture integrity={texture_integrity}."
                self.archive_d3d11_preview_status_label.setText(message)
                self.set_status_message(message, error=texture_integrity == "missing_required")
            else:
                self.archive_d3d11_preview_status_label.setText("")
                self.set_status_message("Isolated D3D11 preview loaded.")
            self._record_archive_memory_audit("d3d11_loaded", d3d11_payload=payload, log_if_high=True)
        elif event == "loading":
            stage = str(payload.get("stage", "") or "loading")
            message = str(payload.get("message", "") or "Loading isolated D3D11 preview...")
            batch_count = int(payload.get("batch_count", 0) or 0)
            vertex_count = int(payload.get("vertex_count", 0) or 0)
            self._set_archive_isolated_renderer_debug(
                "Isolated Renderer: loading one-shot D3D11 preview; "
                f"backend={str(payload.get('backend', 'd3d11') or 'd3d11').upper()}; "
                f"stage={stage}; batches={batch_count:,}; vertices={vertex_count:,}\n"
                f"{message}\n"
                "If Windows Defender quarantines this unsigned experimental build, submit the EXE to Microsoft for analysis before allowing it: "
                "https://www.microsoft.com/wdsi/filesubmission"
            )
            self.archive_d3d11_preview_status_label.setText(message)
            self.set_status_message(f"Isolated D3D11 renderer: {message}")
        elif event == "device_lost":
            stage = str(payload.get("stage", payload.get("device_loss_stage", "render")) or "render")
            hresult = str(payload.get("device_loss_hresult", "") or "")
            removed = str(payload.get("device_removed_reason", "") or "")
            message = f"Native D3D11 device lost during {stage}."
            detail = f"{message} hresult={hresult}; removed={removed}".strip()
            self.archive_d3d11_preview_status_label.setText(message)
            self.set_status_message(message, error=True)
            self._set_archive_isolated_renderer_debug(f"Isolated Renderer device lost: {detail}")
            self._show_archive_d3d11_hard_failure(message)
        elif event == "error":
            message = str(payload.get("message", "") or "Renderer error.")
            discarded_pending = self._discard_archive_d3d11_pending_package(status_file)
            failed_texture_count = int(payload.get("texture_failures", 0) or 0)
            failed_texture_items: List[str] = []
            failed_textures_raw = payload.get("failed_textures", ())
            if isinstance(failed_textures_raw, Sequence) and not isinstance(failed_textures_raw, (str, bytes)):
                for item in tuple(failed_textures_raw)[:8]:
                    if isinstance(item, Mapping):
                        required = "required" if bool(item.get("required", False)) else "optional"
                        failed_texture_items.append(
                            f"{item.get('slot', '?')}:{item.get('source_kind', '?')}:{item.get('stage', '?')}:{item.get('hresult', '')}:{required}:"
                            f"{Path(str(item.get('path', '') or '')).name}"
                        )
            failed_texture_text = (
                f"\nTexture failures: {failed_texture_count:,}; " + ("; ".join(failed_texture_items) or "none")
                if failed_texture_count
                else ""
            )
            self.archive_d3d11_preview_status_label.setText(message)
            self.set_status_message(f"Isolated D3D11 renderer error: {message}", error=True)
            self._set_archive_isolated_renderer_debug(
                f"Isolated Renderer error: {message}{failed_texture_text}\n"
                "Defender note: if Windows Defender quarantines this unsigned experimental build, submit the EXE to Microsoft for analysis before allowing it: "
                "https://www.microsoft.com/wdsi/filesubmission"
            )
            if discarded_pending and getattr(self, "archive_isolated_renderer_active_package", None) is not None:
                self.archive_preview_stack.setCurrentWidget(self.archive_d3d11_preview_host)
            else:
                self._show_archive_d3d11_hard_failure(f"Isolated D3D11 renderer error: {message}")
        elif event == "closed":
            if bool(payload.get("device_lost", False)) or str(payload.get("reason", "") or "") == "device_lost":
                stage = str(payload.get("device_loss_stage", "render") or "render")
                message = f"Native D3D11 preview closed after device loss during {stage}."
                self.archive_d3d11_preview_status_label.setText(message)
                self.set_status_message(message, error=True)
                self._set_archive_isolated_renderer_debug(self._format_archive_isolated_renderer_debug(payload))
            else:
                self.archive_d3d11_preview_status_label.setText("D3D11 preview closed.")
                self.set_status_message("Isolated D3D11 renderer closed.")

    def _handle_archive_isolated_renderer_error(
        self,
        process: QProcess,
        generation: int,
        error: object,
    ) -> None:
        expected_stop = self._consume_archive_isolated_renderer_expected_stop(process, generation)
        if expected_stop is not None:
            reason, status_payload = expected_stop
            self._record_archive_d3d11_runtime_event(
                "d3d11_process_expected_stop_error",
                error=str(error),
                reason=reason,
                process_pid=self._archive_qprocess_pid(process),
                process_generation=int(generation),
            )
            if _archive_status_reports_device_loss(status_payload):
                stage = str(
                    status_payload.get("device_loss_stage", status_payload.get("stage", "render"))
                    or "render"
                )
                message = f"Native D3D11 preview stopped after device loss during {stage}."
                self.archive_d3d11_preview_status_label.setText(message)
                self.set_status_message(message, error=True)
                self._set_archive_isolated_renderer_debug(self._format_archive_isolated_renderer_debug(status_payload))
                self._show_archive_d3d11_hard_failure(message)
            return
        if not self._archive_isolated_renderer_signal_is_current(process, generation):
            return
        self._record_archive_d3d11_runtime_event(
            "d3d11_process_error",
            error=str(error),
            process_pid=self._archive_qprocess_pid(process),
            process_generation=int(generation),
        )
        self.set_status_message(f"Isolated D3D11 renderer process error: {error}", error=True)
        self._set_archive_isolated_renderer_debug(
            f"Isolated Renderer process error: {error}\n"
            "Defender note: if Windows Defender quarantines this unsigned experimental build, submit the EXE to Microsoft for analysis before allowing it: "
            "https://www.microsoft.com/wdsi/filesubmission"
        )
        if not self._archive_isolated_renderer_process_running():
            self.archive_isolated_renderer_process = None
            self.archive_isolated_renderer_active_process = None
            self.archive_isolated_renderer_status_timer.stop()
            had_pending = self._discard_archive_d3d11_pending_package()
            self._cleanup_archive_isolated_renderer_packages(include_active=not had_pending)
            self._show_archive_d3d11_hard_failure(f"Isolated D3D11 renderer process error: {error}")
            self._release_archive_isolated_renderer_process_generation(process, generation)

    def _handle_archive_isolated_renderer_finished(
        self,
        process: QProcess,
        generation: int,
        exit_code: int,
        exit_status: object,
    ) -> None:
        expected_stop = self._consume_archive_isolated_renderer_expected_stop(process, generation)
        if expected_stop is not None:
            reason, status_payload = expected_stop
            self._record_archive_d3d11_runtime_event(
                "d3d11_process_expected_stop_finished",
                exit_code=int(exit_code),
                exit_status=str(exit_status),
                reason=reason,
                process_pid=self._archive_qprocess_pid(process),
                process_generation=int(generation),
            )
            self._release_archive_isolated_renderer_process_generation(process, generation)
            if _archive_status_reports_device_loss(status_payload):
                stage = str(
                    status_payload.get("device_loss_stage", status_payload.get("stage", "render"))
                    or "render"
                )
                message = f"Native D3D11 preview stopped after device loss during {stage} (exit {int(exit_code)})."
                self.archive_d3d11_preview_status_label.setText(message)
                self.set_status_message(message, error=True)
                self._set_archive_isolated_renderer_debug(self._format_archive_isolated_renderer_debug(status_payload))
                self._show_archive_d3d11_hard_failure(message)
            return
        if not self._archive_isolated_renderer_signal_is_current(process, generation):
            self._release_archive_isolated_renderer_process_generation(process, generation)
            return
        self._record_archive_d3d11_runtime_event(
            "d3d11_process_finished",
            exit_code=int(exit_code),
            exit_status=str(exit_status),
            process_pid=self._archive_qprocess_pid(process),
            process_generation=int(generation),
        )
        self._poll_archive_isolated_renderer_status()
        last_status_payload = dict(getattr(self, "archive_isolated_renderer_last_status_payload", {}) or {})
        self.archive_isolated_renderer_process = None
        self.archive_isolated_renderer_active_process = None
        self._release_archive_isolated_renderer_process_generation(process, generation)
        self.archive_isolated_renderer_status_timer.stop()
        self.archive_isolated_renderer_last_status_payload = {}
        had_pending = self._discard_archive_d3d11_pending_package()
        self._cleanup_archive_isolated_renderer_packages(include_active=not had_pending)
        if int(exit_code) == 0 and self.archive_preview_stack.currentWidget() is self.archive_d3d11_preview_host:
            self.archive_preview_stack.setCurrentWidget(self.archive_model_preview)
        self.set_status_message(f"Isolated D3D11 renderer exited with code {int(exit_code)}.")
        if int(exit_code) != 0:
            self.archive_preview_stack.setCurrentWidget(self.archive_d3d11_preview_host)
            if bool(last_status_payload.get("device_lost", False)):
                stage = str(last_status_payload.get("device_loss_stage", last_status_payload.get("stage", "render")) or "render")
                message = f"Native D3D11 preview stopped after device loss during {stage} (exit {int(exit_code)})."
                self.archive_d3d11_preview_status_label.setText(message)
                self.set_status_message(message, error=True)
                self._set_archive_isolated_renderer_debug(self._format_archive_isolated_renderer_debug(last_status_payload))
                self._show_archive_d3d11_hard_failure(message)
            else:
                self.archive_d3d11_preview_status_label.setText(f"Native D3D11 preview failed to load (exit {int(exit_code)}).")
                self._set_archive_isolated_renderer_debug(
                    f"Isolated Renderer: process exited with code {int(exit_code)} ({exit_status}).\n"
                    "Defender note: if Windows Defender quarantines this unsigned experimental build, submit the EXE to Microsoft for analysis before allowing it: "
                    "https://www.microsoft.com/wdsi/filesubmission"
                )
                self._show_archive_d3d11_hard_failure(f"Native D3D11 preview failed to load (exit {int(exit_code)}).")

    def _shutdown_archive_isolated_renderer_host(self) -> None:
        process = getattr(self, "archive_isolated_renderer_process", None)
        if process is None:
            self.archive_isolated_renderer_status_timer.stop()
            self._cleanup_archive_isolated_renderer_packages(include_active=True)
            self._release_archive_d3d11_package_leases()
            return
        generation = self._archive_isolated_renderer_generation_for_process(process)
        package_dir = getattr(self, "archive_isolated_renderer_active_package", None)
        self._poll_archive_isolated_renderer_status()
        self._mark_archive_isolated_renderer_expected_stop(
            process,
            generation,
            reason="shutdown",
        )
        self._record_archive_d3d11_runtime_event(
            "d3d11_process_shutdown_begin",
            package_dir=str(package_dir or ""),
            process_pid=self._archive_qprocess_pid(process),
            process_generation=generation,
            process_state=str(self._archive_qprocess_state(process)),
        )
        self.archive_isolated_renderer_process = None
        self.archive_isolated_renderer_active_process = None
        self.archive_isolated_renderer_active_package = None
        self.archive_d3d11_active_model_key = ""
        self.archive_d3d11_pending_model_key = ""
        self.archive_isolated_renderer_status_file = None
        self.archive_isolated_renderer_status_signature = (0, 0)
        self.archive_isolated_renderer_status_payload_text = ""
        self.archive_isolated_renderer_last_status_payload = {}
        self.archive_isolated_renderer_status_timer.stop()
        state = self._archive_qprocess_state(process)
        try:
            if state != QProcess.NotRunning:
                def cleanup_finished_process(*_args: object) -> None:
                    self._release_archive_d3d11_package_leases()
                    self._cleanup_finished_archive_isolated_renderer_process(
                        process,
                        package_dir,
                        generation,
                    )

                def kill_process_if_still_running() -> None:
                    self._kill_archive_isolated_renderer_process_if_running(
                        process,
                        generation=generation,
                        reason="shutdown_force_kill",
                    )

                def remove_retired_package_dir() -> None:
                    self._remove_archive_isolated_package_dir(package_dir)

                process.finished.connect(cleanup_finished_process)
                process.terminate()
                QTimer.singleShot(1200, kill_process_if_still_running)
                QTimer.singleShot(7000, remove_retired_package_dir)
            else:
                self._release_archive_isolated_renderer_process_generation(process, generation)
                self._release_archive_d3d11_package_leases()
                self._remove_archive_isolated_package_dir(package_dir)
                self._delete_archive_qprocess_later(process)
        except RuntimeError:
            self._release_archive_isolated_renderer_process_generation(process, generation)
            self._release_archive_d3d11_package_leases()
            self._remove_archive_isolated_package_dir(package_dir)
            self._delete_archive_qprocess_later(process)
        self._cleanup_archive_isolated_renderer_packages(include_active=False)
        self.archive_d3d11_preview_status_label.setText("D3D11 preview is not running.")
        self._record_archive_d3d11_runtime_event(
            "d3d11_process_shutdown_queued",
            package_dir=str(package_dir or ""),
            process_generation=generation,
            process_state=str(state),
        )
