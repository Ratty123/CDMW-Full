"""D3D11 archive preview package worker coordination."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QThread, QTimer

from cdmw.models import ArchivePreviewResult, PreparedModelPreviewData
from cdmw.workers.d3d11_package_workers import ArchiveD3D11PackageWorker


class ArchivePreviewD3D11WorkerMixin:
    """Start, queue, and collect D3D11 preview package workers."""

    def _start_archive_isolated_preview_package_worker(self, result: ArchivePreviewResult) -> None:
        preview_model = getattr(result, "preview_model", None)
        prepared_preview = getattr(result, "prepared_preview_model", None)
        if preview_model is None or not isinstance(prepared_preview, PreparedModelPreviewData):
            self.set_status_message("No prepared model preview is available for the isolated D3D11 renderer.", error=True)
            return
        if self.archive_isolated_package_thread is not None:
            self.archive_isolated_package_request_id += 1
            self.archive_isolated_package_pending_result = result
            recorder = getattr(self, "_record_runtime_event", None)
            if callable(recorder):
                recorder(
                    "d3d11_package_worker_queue_latest",
                    package_request_id=self.archive_isolated_package_request_id,
                    archive_preview_request_id=self.archive_preview_request_id,
                    source_path=getattr(preview_model, "path", ""),
                )
            if self.archive_isolated_package_worker is not None:
                self.archive_isolated_package_worker.stop()
            self.archive_d3d11_preview_status_label.setText("Queued latest D3D11 preview package...")
            self.set_status_message("Queued latest D3D11 preview package; waiting for the previous package job to stop.")
            return

        settings = self._current_model_preview_render_settings()
        renderer_backend = self._archive_model_renderer_backend()
        self.archive_isolated_package_request_id += 1
        request_id = self.archive_isolated_package_request_id
        archive_preview_request_id = int(self.archive_preview_request_id)
        set_last_active = getattr(self, "_set_last_active_operation", None)
        if callable(set_last_active):
            set_last_active(
                "d3d11_package_prepare",
                package_request_id=request_id,
                archive_preview_request_id=archive_preview_request_id,
                source_path=getattr(preview_model, "path", ""),
                batches=len(getattr(prepared_preview, "batches", ()) or ()),
                backend=renderer_backend,
            )
        worker = ArchiveD3D11PackageWorker(
            request_id,
            archive_preview_request_id,
            preview_model,
            prepared_preview,
            settings,
            use_textures=bool(settings.use_textures_by_default),
            high_quality_textures=bool(settings.high_quality_by_default),
            backend="d3d11",
            prefer_direct_dds=True,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_archive_isolated_package_ready)
        worker.error.connect(self._handle_archive_isolated_package_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_archive_isolated_package_worker_refs)
        self.archive_isolated_package_worker = worker
        self.archive_isolated_package_thread = thread
        self.archive_preview_stack.setCurrentWidget(self.archive_d3d11_preview_host)
        self.archive_d3d11_preview_status_label.setText("Preparing native D3D11 preview package...")
        self._set_archive_isolated_renderer_debug(
            "Native D3D11 Preview: preparing package in a background thread. "
            + "The Archive Browser should remain responsive while geometry and texture references are staged."
        )
        self.set_status_message("Preparing native D3D11 preview package...")
        thread.start()

    def _launch_archive_isolated_preview_result(self, result: ArchivePreviewResult) -> None:
        if not self._archive_isolated_renderer_process_running():
            self._shutdown_archive_isolated_renderer_host()
        self._start_archive_isolated_preview_package_worker(result)

    def _handle_archive_isolated_package_ready(
        self,
        request_id: int,
        archive_preview_request_id: int,
        package_dir_object: object,
        elapsed_ms: float,
    ) -> None:
        try:
            package_dir = Path(package_dir_object)
        except TypeError:
            return
        recorder = getattr(self, "_record_runtime_event", None)
        if (
            int(request_id) != int(getattr(self, "archive_isolated_package_request_id", 0) or 0)
            or int(archive_preview_request_id) != int(self.archive_preview_request_id)
        ):
            if callable(recorder):
                recorder(
                    "d3d11_package_ready_stale",
                    package_request_id=request_id,
                    archive_preview_request_id=archive_preview_request_id,
                    current_package_request_id=getattr(self, "archive_isolated_package_request_id", 0),
                    current_archive_preview_request_id=self.archive_preview_request_id,
                    package_dir=str(package_dir),
                )
            try:
                shutil.rmtree(package_dir, ignore_errors=True)
            except OSError:
                pass
            return
        valid_package, missing_paths = self._validate_d3d11_preview_package_paths(package_dir)
        if not valid_package:
            message = "D3D11 package manifest references missing files: " + "; ".join(missing_paths[:6])
            if callable(recorder):
                recorder(
                    "d3d11_package_invalid_paths",
                    package_request_id=request_id,
                    archive_preview_request_id=archive_preview_request_id,
                    package_dir=str(package_dir),
                    missing=list(missing_paths[:12]),
                )
            try:
                shutil.rmtree(package_dir, ignore_errors=True)
            except OSError:
                pass
            self.set_status_message(message, error=True)
            self.archive_d3d11_preview_status_label.setText("D3D11 package validation failed.")
            self._set_archive_isolated_renderer_debug(
                "Native D3D11 Preview: package validation failed before launch.\n" + message
            )
            self._show_archive_d3d11_hard_failure(message)
            return
        if self._archive_isolated_renderer_process_running():
            self._set_archive_d3d11_pending_package(package_dir, package_dir / "host_status.json", "python-prepared")
        else:
            previous = getattr(self, "archive_isolated_renderer_active_package", None)
            if previous is not None:
                self.archive_isolated_renderer_retired_packages.append(previous)
            self.archive_isolated_renderer_active_package = package_dir
            self.archive_isolated_renderer_package_source = "python-prepared"
        if callable(recorder):
            recorder(
                "d3d11_package_ready",
                package_request_id=request_id,
                archive_preview_request_id=archive_preview_request_id,
                package_dir=str(package_dir),
                elapsed_ms=round(float(elapsed_ms), 3),
            )
        self.set_status_message(f"Prepared native D3D11 preview package in {float(elapsed_ms):.1f} ms.")
        self._set_archive_isolated_renderer_debug(
            "D3D11 package source: python-prepared\n"
            "Native D3D11 Preview: loading package generated from Python's full material resolver."
        )
        self._start_archive_isolated_renderer_process(package_dir)

    def _handle_archive_isolated_package_error(
        self,
        request_id: int,
        archive_preview_request_id: int,
        message: str,
    ) -> None:
        if (
            int(request_id) != int(getattr(self, "archive_isolated_package_request_id", 0) or 0)
            or int(archive_preview_request_id) != int(self.archive_preview_request_id)
        ):
            return
        recorder = getattr(self, "_record_runtime_event", None)
        if callable(recorder):
            recorder(
                "d3d11_package_error",
                package_request_id=request_id,
                archive_preview_request_id=archive_preview_request_id,
                message=message,
            )
        self.set_status_message(f"Failed to prepare native D3D11 preview package: {message}", error=True)
        self.archive_d3d11_preview_status_label.setText("D3D11 package preparation failed.")
        self._set_archive_isolated_renderer_debug(f"Native D3D11 Preview: package preparation failed: {message}")
        self._show_archive_d3d11_hard_failure("Native D3D11 package preparation failed.")

    def _cleanup_archive_isolated_package_worker_refs(self) -> None:
        self.archive_isolated_package_thread = None
        self.archive_isolated_package_worker = None
        pending_result = self.archive_isolated_package_pending_result
        self.archive_isolated_package_pending_result = None
        if pending_result is not None and not self._shutting_down:
            QTimer.singleShot(0, lambda result=pending_result: self._launch_archive_isolated_preview_result(result))
