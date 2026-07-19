"""Archive browser worker ownership boundary."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, QTimer

from cdmw.models import ArchiveEntry, ArchivePreviewResult
from cdmw.ui.archive_browser.remote_preview_dependencies import ArchivePreviewDependencySet
from cdmw.ui.model_preview_native import ARCHIVE_MODEL_RENDERER_D3D11
from cdmw.workers.archive_preview_native import NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS
from cdmw.workers.archive_preview_workers import ArchivePreviewWorker, _ArchivePreviewWorkerPayload


def _archive_preview_debounce_ms(entry: Optional[ArchiveEntry]) -> int:
    extension = str(getattr(entry, "extension", "") or "").strip().lower()
    return 450 if extension in NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS else 90


def _record_archive_worker_lifecycle(target: object, event: str, **fields: object) -> None:
    recorder = getattr(target, "_record_runtime_event", None)
    if callable(recorder):
        try:
            recorder(str(event), **fields)
        except Exception:
            return


class ArchiveWorkerLifecycleMixin:
    """Small archive-browser worker stop helpers owned outside the shell window."""

    def _stop_archive_basic_index_worker(self) -> None:
        self.archive_basic_index_request_id = int(getattr(self, "archive_basic_index_request_id", 0) or 0) + 1
        if self.archive_basic_index_worker is not None:
            _record_archive_worker_lifecycle(
                self,
                "archive_worker_cancelled",
                reason="cancelled_by_new_scan",
                worker="basic_index",
            )
            try:
                self.archive_basic_index_worker.stop()
            except Exception as exc:
                _record_archive_worker_lifecycle(
                    self,
                    "archive_worker_failed",
                    reason="worker_failed",
                    worker="basic_index",
                    error=str(exc),
                )

    def _stop_archive_sidecar_worker(self) -> None:
        if self.archive_sidecar_worker is not None:
            _record_archive_worker_lifecycle(self, "archive_worker_cancelled", reason="cancelled_by_shutdown", worker="sidecar")
            try:
                self.archive_sidecar_worker.stop()
            except Exception as exc:
                _record_archive_worker_lifecycle(self, "archive_worker_failed", reason="worker_failed", worker="sidecar", error=str(exc))

    def _stop_archive_derived_cache_worker(self) -> None:
        self.archive_derived_cache_write_pending = False
        self.archive_enhanced_index_request_id = int(
            getattr(self, "archive_enhanced_index_request_id", 0) or 0
        ) + 1
        if self.archive_derived_cache_worker is not None:
            _record_archive_worker_lifecycle(self, "archive_worker_cancelled", reason="cancelled_by_shutdown", worker="derived_cache")
            try:
                self.archive_derived_cache_worker.stop()
            except Exception as exc:
                _record_archive_worker_lifecycle(self, "archive_worker_failed", reason="worker_failed", worker="derived_cache", error=str(exc))
        if self.archive_enhanced_index_worker is not None:
            _record_archive_worker_lifecycle(self, "archive_worker_cancelled", reason="cancelled_by_shutdown", worker="enhanced_index")
            try:
                self.archive_enhanced_index_worker.stop()
            except Exception as exc:
                _record_archive_worker_lifecycle(self, "archive_worker_failed", reason="worker_failed", worker="enhanced_index", error=str(exc))
        if self.archive_structure_filter_worker is not None:
            _record_archive_worker_lifecycle(self, "archive_worker_cancelled", reason="cancelled_by_shutdown", worker="structure_filter")
            try:
                self.archive_structure_filter_worker.stop()
            except Exception as exc:
                _record_archive_worker_lifecycle(self, "archive_worker_failed", reason="worker_failed", worker="structure_filter", error=str(exc))


class ArchivePreviewWorkerMixin:
    """Archive preview worker start, result, error, and queued-request handling."""

    def _render_archive_preview(
        self,
        entry: Optional[ArchiveEntry],
        *,
        include_loose_preview_assets: bool = False,
        prefer_loose_preview: bool = False,
        force: bool = False,
    ) -> None:
        self._ensure_archive_preview_startup_state()
        if not force and self._mesh_replacement_builder_active():
            self._defer_archive_preview_refresh_for_builder(entry)
            return
        remote_bridge = getattr(self, "archive_remote_bridge", None)
        if remote_bridge is not None and remote_bridge.displays_v2:
            remote_bridge.cancel_preview_dependencies(clear_snapshot=True)
        request_id = self.archive_preview_request_id + 1
        self.archive_preview_request_id = request_id
        self.append_archive_log(
            f"Archive Browser activation timing | cause=preview_start | path={getattr(entry, 'path', '')}",
            verbose=True,
        )
        self._set_last_active_operation(
            "archive_preview_request",
            request_id=request_id,
            path=getattr(entry, "path", ""),
            backend=self._archive_model_renderer_backend(),
            include_loose_preview_assets=include_loose_preview_assets,
            prefer_loose_preview=prefer_loose_preview,
        )
        self.archive_preview_cache_keys = {
            existing_request_id: cache_key
            for existing_request_id, cache_key in self.archive_preview_cache_keys.items()
            if existing_request_id >= request_id
        }
        self.archive_preview_request_started_at = {
            existing_request_id: started_at
            for existing_request_id, started_at in self.archive_preview_request_started_at.items()
            if existing_request_id >= request_id
        }
        self.archive_preview_request_phase_timings = {
            existing_request_id: timing_map
            for existing_request_id, timing_map in self.archive_preview_request_phase_timings.items()
            if existing_request_id >= request_id
        }
        self.archive_preview_request_sources = {
            existing_request_id: source
            for existing_request_id, source in self.archive_preview_request_sources.items()
            if existing_request_id >= request_id
        }
        self.archive_preview_request_started_at[request_id] = time.perf_counter()
        self.archive_preview_request_phase_timings[request_id] = {}
        self.archive_preview_request_sources[request_id] = "worker"
        if (
            self._archive_model_renderer_backend() == ARCHIVE_MODEL_RENDERER_D3D11
            and entry is not None
            and str(getattr(entry, "extension", "") or "").strip().lower() in NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS
        ):
            self._note_native_preview_core_activity()
        self.archive_preview_quick_result_active = False
        self.archive_preview_requested_loose = bool(entry is not None and prefer_loose_preview)
        self.pending_archive_preview_request = None
        self.scheduled_archive_preview_request = (request_id, entry, include_loose_preview_assets, bool(force))
        self._show_archive_preview_loading_state(entry)
        self.archive_preview_debounce_timer.start(_archive_preview_debounce_ms(entry))

    def _flush_scheduled_archive_preview_request(self) -> None:
        if self.scheduled_archive_preview_request is None:
            return
        request_id, entry, include_loose_preview_assets, force = self.scheduled_archive_preview_request
        remote_dependencies: ArchivePreviewDependencySet | None = None
        remote_bridge = getattr(self, "archive_remote_bridge", None)
        if remote_bridge is not None and remote_bridge.displays_v2 and entry is not None:
            remote_dependencies = remote_bridge.preview_dependencies_for(request_id, entry)
            if remote_dependencies is None:
                if not remote_bridge.preview_dependencies_pending_for(request_id):
                    started = remote_bridge.request_preview_dependencies(request_id, entry)
                    if started:
                        detail = "Resolving bounded archive preview dependencies..."
                        self._set_archive_preview_base_detail_text(
                            detail,
                            include_current_model_debug=False,
                        )
                        self.set_status_message(detail)
                return
            entry = remote_dependencies.selected_entry
        if (
            entry is not None
            and str(getattr(entry, "extension", "") or "").strip().lower()
            in NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS
            and self._archive_basic_index_missing_for_lookup()
        ):
            self._ensure_archive_basic_index_worker_started()
            self._set_archive_preview_base_detail_text(
                "Preparing archive material and texture lookup...",
                include_current_model_debug=False,
            )
            self.set_status_message("Preparing archive material and texture lookup...")
            return
        self.scheduled_archive_preview_request = None
        if not force and self._mesh_replacement_builder_active():
            self._defer_archive_preview_refresh_for_builder(entry)
            return

        loose_search_roots = self._collect_archive_preview_loose_roots()
        cache_key = self._archive_preview_cache_key(
            entry,
            loose_search_roots,
            include_loose_preview_assets=include_loose_preview_assets,
            sidecar_generation=self.archive_sidecar_generation,
            quality_tier="full",
        )
        self.archive_preview_cache_keys[request_id] = cache_key

        texture_entries_by_normalized_path = (
            remote_dependencies.entries_by_normalized_path
            if remote_dependencies is not None
            else self.archive_entries_by_normalized_path
        )
        texture_entries_by_basename = (
            remote_dependencies.entries_by_basename
            if remote_dependencies is not None
            else self.archive_entries_by_basename
        )
        companion_entry = self._find_archive_preview_companion_entry(
            entry,
            entries_by_normalized_path=(
                texture_entries_by_normalized_path if remote_dependencies is not None else None
            ),
        )
        fast_cache_key = self._archive_preview_cache_key(
            entry,
            loose_search_roots,
            include_loose_preview_assets=include_loose_preview_assets,
            sidecar_generation=self.archive_sidecar_generation,
            quality_tier="fast",
        )
        performance_settings = self._current_archive_performance_settings()
        preview_cache_snapshot = {
            key: self.archive_preview_cache[key]
            for key in (cache_key, fast_cache_key)
            if key and key in self.archive_preview_cache
        }
        cache_miss_reason = ""
        cache_miss_detail = ""
        for preview_cache_key, cached_result in tuple(preview_cache_snapshot.items()):
            native_package_path = str(getattr(cached_result, "native_preview_package_path", "") or "").strip()
            if not native_package_path:
                continue
            valid_package, missing_paths = self._validate_d3d11_preview_package_paths(Path(native_package_path))
            if valid_package:
                continue
            preview_cache_snapshot.pop(preview_cache_key, None)
            self.archive_preview_cache.pop(preview_cache_key, None)
            cache_miss_reason = "native_package_expired"
            cache_miss_detail = "; ".join(missing_paths[:4])
            self._record_runtime_event(
                "archive_preview_cache_native_package_expired",
                request_id=request_id,
                selected_path=str(getattr(entry, "path", "") or ""),
                cache_key=preview_cache_key,
                package_path=native_package_path,
                missing=list(missing_paths[:12]),
            )

        if self.archive_preview_thread is not None:
            self.pending_archive_preview_request = (request_id, entry, include_loose_preview_assets)
            _record_archive_worker_lifecycle(
                self,
                "archive_preview_worker_cancelled",
                reason="cancelled_by_new_request",
                request_id=request_id,
                previous_request_id=self.archive_preview_request_id,
                path=getattr(entry, "path", ""),
            )
            if self.archive_preview_worker is not None:
                self.archive_preview_worker.stop()
            return

        self._show_archive_preview_loading_state(entry)
        if cache_miss_reason == "native_package_expired":
            rebuild_text = "Cached preview package expired; rebuilding preview package..."
            self.archive_preview_meta_label.setText("Rebuilding preview package...")
            self._set_archive_preview_health_message(
                "Rebuilding native D3D11 preview package...",
                visible=bool(entry),
            )
            self._set_archive_preview_base_detail_text(
                f"{rebuild_text}\n{cache_miss_detail}".strip(),
                include_current_model_debug=False,
            )
            self.archive_preview_info_edit.setPlainText(f"{rebuild_text}\n{cache_miss_detail}".strip())
            self.set_status_message("Cached preview package expired; rebuilding preview package.")

        self._start_archive_preview_worker(
            request_id,
            entry,
            loose_search_roots,
            include_loose_preview_assets=include_loose_preview_assets,
            companion_entry=companion_entry,
            full_cache_key=cache_key,
            fast_cache_key=fast_cache_key,
            preview_cache_snapshot=preview_cache_snapshot,
            emit_quick_preview=(
                performance_settings.quick_then_full_preview
                and not include_loose_preview_assets
                and fast_cache_key not in preview_cache_snapshot
            ),
            texture_entries_by_normalized_path=texture_entries_by_normalized_path,
            texture_entries_by_basename=texture_entries_by_basename,
            sidecar_entries_by_texture_path=(
                {} if remote_dependencies is not None else self.archive_sidecar_entries_by_texture_path
            ),
            sidecar_entries_by_texture_basename=(
                {} if remote_dependencies is not None else self.archive_sidecar_entries_by_texture_basename
            ),
        )

    def _handle_archive_remote_preview_dependencies_ready(
        self,
        request_id: int,
        payload: object,
    ) -> None:
        if self._shutting_down or int(request_id) != int(self.archive_preview_request_id):
            return
        if not isinstance(payload, ArchivePreviewDependencySet):
            self._handle_archive_remote_preview_dependencies_failed(
                request_id,
                "The archive worker returned an invalid preview dependency set.",
            )
            return
        if payload.truncated:
            self._handle_archive_remote_preview_dependencies_failed(
                request_id,
                "Archive preview dependency lookup exceeded the 4,096-entry safety bound.",
            )
            return
        scheduled = self.scheduled_archive_preview_request
        if scheduled is None or int(scheduled[0]) != int(request_id):
            return
        self._record_runtime_event(
            "archive_preview_dependencies_ready",
            request_id=request_id,
            entry_id=payload.entry_id,
            candidate_count=max(0, len(payload.entries) - 1),
            total_candidates=payload.total_candidates,
        )
        update_controls = getattr(self, "_update_archive_model_action_controls", None)
        controls_target = getattr(self, "_archive_model_preview_controls_target", None)
        if callable(update_controls) and callable(controls_target):
            update_controls(controls_target())
        self._flush_scheduled_archive_preview_request()

    def _handle_archive_remote_preview_dependencies_failed(
        self,
        request_id: int,
        message: str,
    ) -> None:
        if self._shutting_down or int(request_id) != int(self.archive_preview_request_id):
            return
        self._record_runtime_event(
            "archive_preview_dependencies_failed",
            request_id=request_id,
            message=str(message),
        )
        self.scheduled_archive_preview_request = None
        self.pending_archive_preview_request = None
        self._stop_archive_preview_loading_indicator(success=False)
        self._clear_archive_preview(f"Preview dependencies could not be resolved: {message}")
        self.set_status_message(f"Archive preview failed: {message}", error=True)

    def _start_archive_preview_worker(
        self,
        request_id: int,
        entry: Optional[ArchiveEntry],
        loose_search_roots: Sequence[Path],
        *,
        include_loose_preview_assets: bool = False,
        companion_entry: Optional[ArchiveEntry] = None,
        full_cache_key: str = "",
        fast_cache_key: str = "",
        preview_cache_snapshot: Optional[Mapping[str, ArchivePreviewResult]] = None,
        emit_quick_preview: bool = False,
        texture_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
        texture_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
        sidecar_entries_by_texture_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
        sidecar_entries_by_texture_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    ) -> None:
        if companion_entry is None:
            companion_entry = self._find_archive_preview_companion_entry(
                entry,
                entries_by_normalized_path=texture_entries_by_normalized_path,
            )
        preview_settings = self._current_model_preview_render_settings()
        native_cache_mode = self._native_preview_package_cache_mode()
        native_cache_max_bytes, native_cache_target_bytes = self._native_preview_package_cache_budget()
        native_package_cache_key = ""
        if (
            native_cache_mode != "off"
            and self._archive_model_renderer_backend() == ARCHIVE_MODEL_RENDERER_D3D11
            and entry is not None
            and str(getattr(entry, "extension", "") or "").strip().lower() in NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS
            and not include_loose_preview_assets
        ):
            native_package_cache_key = self._archive_native_preview_package_cache_key(
                entry,
                companion_entry,
                loose_search_roots,
                include_loose_preview_assets=include_loose_preview_assets,
            )
        self._record_runtime_event(
            "archive_preview_worker_start",
            request_id=request_id,
            path=getattr(entry, "path", ""),
            companion_path=getattr(companion_entry, "path", ""),
            backend=self._archive_model_renderer_backend(),
            native_preview_core_enabled=(self._archive_model_renderer_backend() == ARCHIVE_MODEL_RENDERER_D3D11),
            native_preview_cache_mode=native_cache_mode,
            native_preview_package_cache_key=native_package_cache_key,
        )
        worker = ArchivePreviewWorker(
            request_id,
            entry,
            companion_entry,
            self.archive_entries_by_normalized_path
            if texture_entries_by_normalized_path is None
            else texture_entries_by_normalized_path,
            self.archive_entries_by_basename
            if texture_entries_by_basename is None
            else texture_entries_by_basename,
            self.archive_sidecar_entries_by_texture_path
            if sidecar_entries_by_texture_path is None
            else sidecar_entries_by_texture_path,
            self.archive_sidecar_entries_by_texture_basename
            if sidecar_entries_by_texture_basename is None
            else sidecar_entries_by_texture_basename,
            loose_search_roots,
            visible_texture_mode=preview_settings.visible_texture_mode,
            support_texture_slots=self._archive_preview_support_texture_slots(preview_settings),
            render_settings=preview_settings,
            include_loose_preview_assets=include_loose_preview_assets,
            sidecar_generation=self.archive_sidecar_generation,
            native_preview_core_enabled=(self._archive_model_renderer_backend() == ARCHIVE_MODEL_RENDERER_D3D11),
            native_preview_core_cache_root=self.archive_cache_root / "native_preview_core",
            native_preview_core_package_root=(
                Path(self.archive_package_root_edit.text().strip()).expanduser()
                if self.archive_package_root_edit.text().strip()
                else None
            ),
            native_preview_package_cache_key=native_package_cache_key,
            native_preview_package_cache_mode=native_cache_mode,
            native_preview_package_cache_max_bytes=native_cache_max_bytes,
            native_preview_package_cache_target_bytes=native_cache_target_bytes,
            full_preview_cache_key=full_cache_key,
            fast_preview_cache_key=fast_cache_key,
            preview_cache_snapshot=preview_cache_snapshot,
            emit_quick_preview=emit_quick_preview,
            emit_private_payloads=True,
        )
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_archive_preview_ready)
        worker.error.connect(self._handle_archive_preview_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._cleanup_archive_preview_refs)

        self.archive_preview_worker = worker
        self.archive_preview_thread = thread
        thread.start()

    def _handle_archive_preview_ready(self, request_id: int, payload: object) -> None:
        full_cache_key = self.archive_preview_cache_keys.get(request_id, "")
        payload_cache_key = ""
        payload_cacheable = True
        if isinstance(payload, _ArchivePreviewWorkerPayload):
            payload_cache_key = str(payload.cache_key or "").strip()
            payload_cacheable = bool(payload.cacheable)
            source = str(payload.source or "worker").strip() or "worker"
            payload = payload.result
        else:
            source = self.archive_preview_request_sources.get(request_id, "worker")
        quality_tier = (
            str(getattr(payload, "quality_tier", "") or "").strip().lower()
            if isinstance(payload, ArchivePreviewResult)
            else "full"
        )
        is_fast_result = quality_tier == "fast"
        is_interim_result = is_fast_result or quality_tier == "quick" or source == "quick_preview"
        if payload_cache_key:
            cache_key = payload_cache_key
        elif is_fast_result and full_cache_key:
            cache_key = full_cache_key.replace("quality:full", "quality:fast")
        else:
            cache_key = full_cache_key
        request_started_at = self.archive_preview_request_started_at.get(request_id)
        request_phase_timings = self.archive_preview_request_phase_timings.get(request_id, {})
        if not is_interim_result:
            self.archive_preview_cache_keys.pop(request_id, None)
            self.archive_preview_request_started_at.pop(request_id, None)
            self.archive_preview_request_phase_timings.pop(request_id, None)
            self.archive_preview_request_sources.pop(request_id, None)
        native_preview_diagnostics = (
            dict(getattr(payload, "native_preview_diagnostics", {}) or {})
            if isinstance(payload, ArchivePreviewResult)
            else {}
        )
        if native_preview_diagnostics.get("native_preview_core_process_pid") or native_preview_diagnostics.get("preview_core_process_pid"):
            self._schedule_native_preview_core_idle_shutdown()
        self._record_runtime_event(
            "archive_preview_ready",
            request_id=request_id,
            source=source,
            current_request_id=self.archive_preview_request_id,
            stale=bool(request_id != self.archive_preview_request_id),
            preview_core_process_working_set_bytes=native_preview_diagnostics.get("process_working_set_bytes", 0),
            preview_core_process_private_bytes=native_preview_diagnostics.get("process_private_bytes", 0),
            native_preview_core_process_pid=native_preview_diagnostics.get("native_preview_core_process_pid", 0),
            preview_core_decoded_cache_bytes=native_preview_diagnostics.get("decoded_cache_bytes", 0),
            preview_core_service_job_count=native_preview_diagnostics.get("service_job_count", 0),
            preview_core_service_recycle_reason=native_preview_diagnostics.get("service_recycle_reason", ""),
        )
        if self._shutting_down or request_id != self.archive_preview_request_id:
            _record_archive_worker_lifecycle(
                self,
                "archive_preview_result_ignored",
                reason="cancelled_by_shutdown" if self._shutting_down else "stale_result_ignored",
                request_id=request_id,
                current_request_id=self.archive_preview_request_id,
                source=source,
            )
            return
        try:
            if isinstance(payload, ArchivePreviewResult):
                result = payload
                if (
                    source != "preview_cache"
                    and int(getattr(result, "sidecar_generation", 0) or 0) < int(self.archive_sidecar_generation)
                ):
                    current_entry = self._current_archive_entry()
                    if current_entry is not None and not self.archive_preview_showing_loose:
                        QTimer.singleShot(0, lambda entry=current_entry: self._render_archive_preview(entry))
                    return
                if payload_cacheable:
                    self._store_cached_archive_preview_result(cache_key, result)
                if source == "quick_preview":
                    self.archive_preview_quick_result_active = True
                self._apply_archive_preview_result(
                    result,
                    request_id=request_id,
                    source=source,
                    base_timings=request_phase_timings,
                    request_started_at=request_started_at,
                )
                if source == "quick_preview":
                    self.set_status_message("Quick preview loaded; building full 3D preview...")
                elif is_fast_result:
                    self.set_status_message("Fast preview loaded; refining full-quality preview...")
                else:
                    self._stop_archive_preview_loading_indicator(success=True)
                    self._record_archive_memory_audit("archive_preview_ready", log_if_high=True)
                    if (
                        self._archive_model_renderer_backend() == ARCHIVE_MODEL_RENDERER_D3D11
                        and self._native_preview_package_cache_mode() == "aggressive"
                    ):
                        self.archive_native_prefetch_timer.start()
        except Exception as exc:
            self._write_crash_report(
                "archive_preview_ready_error",
                "Archive preview apply error",
                str(exc),
                context=self._collect_crash_context(),
            )
            self._clear_archive_preview(f"Preview failed: {exc}")
            self.set_status_message(f"Archive preview failed: {exc}", error=True)

    def _handle_archive_preview_error(self, request_id: int, message: str) -> None:
        self.archive_preview_cache_keys.pop(request_id, None)
        self.archive_preview_request_started_at.pop(request_id, None)
        self.archive_preview_request_phase_timings.pop(request_id, None)
        self.archive_preview_request_sources.pop(request_id, None)
        self._record_runtime_event(
            "archive_preview_error",
            request_id=request_id,
            current_request_id=self.archive_preview_request_id,
            message=message,
        )
        if self._shutting_down or request_id != self.archive_preview_request_id:
            _record_archive_worker_lifecycle(
                self,
                "archive_preview_worker_failed",
                reason="cancelled_by_shutdown" if self._shutting_down else "stale_result_ignored",
                request_id=request_id,
                current_request_id=self.archive_preview_request_id,
                message=str(message),
            )
            return
        self._stop_archive_preview_loading_indicator(success=False)
        self._write_crash_report(
            "archive_preview_error",
            "Archive preview error",
            str(message),
            context=self._collect_crash_context(),
        )
        current_quality = str(getattr(self.current_archive_preview_result, "quality_tier", "") or "").strip().lower()
        if current_quality in {"fast", "quick"}:
            label = "fast" if current_quality == "fast" else "quick"
            self.set_status_message(f"Full preview failed after {label} preview: {message}", error=True)
            return
        self._clear_archive_preview(f"Preview failed: {message}")

    def _cleanup_archive_preview_refs(
        self,
        thread: Optional[QThread] = None,
        worker: Optional[ArchivePreviewWorker] = None,
    ) -> None:
        if thread is None:
            sender = self.sender()
            thread = sender if isinstance(sender, QThread) else self.archive_preview_thread
        worker = self.archive_preview_worker if worker is None else worker
        if thread is not None:
            try:
                if not thread.wait(0):
                    QTimer.singleShot(
                        1,
                        lambda target_thread=thread, target_worker=worker: self._cleanup_archive_preview_refs(
                            target_thread,
                            target_worker,
                        ),
                    )
                    return
            except RuntimeError:
                pass
        if self.archive_preview_thread is not thread or self.archive_preview_worker is not worker:
            if thread is not None:
                try:
                    thread.deleteLater()
                except RuntimeError:
                    pass
            return
        self.archive_preview_thread = None
        self.archive_preview_worker = None
        if thread is not None:
            try:
                thread.deleteLater()
            except RuntimeError:
                pass
        if self._shutting_down:
            _record_archive_worker_lifecycle(
                self,
                "archive_preview_worker_cancelled",
                reason="cancelled_by_shutdown",
                pending=bool(self.pending_archive_preview_request),
                scheduled=bool(self.scheduled_archive_preview_request),
            )
            self.pending_archive_preview_request = None
            self.scheduled_archive_preview_request = None
            return
        if self.pending_archive_preview_request is None:
            return
        request_id, entry, include_loose_preview_assets = self.pending_archive_preview_request
        self.pending_archive_preview_request = None
        self.scheduled_archive_preview_request = (
            request_id,
            entry,
            include_loose_preview_assets,
            False,
        )
        self._flush_scheduled_archive_preview_request()


__all__ = ["ArchivePreviewWorkerMixin", "ArchiveWorkerLifecycleMixin"]
