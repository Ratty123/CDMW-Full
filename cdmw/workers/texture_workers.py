"""Texture worker extraction point."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.core.pipeline import convert_dds_to_pngs, rebuild_dds_files, scan_dds_files
from cdmw.models import AppConfig


def _write_texture_workflow_breadcrumb(
    crash_reports_dir: Optional[Path],
    session_id: str,
    payload: Mapping[str, object],
) -> None:
    if crash_reports_dir is None:
        return
    try:
        crash_reports_dir.mkdir(parents=True, exist_ok=True)
        breadcrumb_path = crash_reports_dir / "texture_workflow_breadcrumb.json"
        enriched = dict(payload)
        enriched.setdefault("timestamp", time.time())
        enriched.setdefault("pid", os.getpid())
        enriched.setdefault("session_id", session_id)
        temp_path = breadcrumb_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(breadcrumb_path)
    except Exception:
        pass


def _texture_workflow_breadcrumb_base(config: AppConfig, worker_name: str) -> Dict[str, object]:
    return {
        "worker": worker_name,
        "status": "running",
        "backend": config.upscale_backend,
        "original_dds_root": config.original_dds_root,
        "png_root": config.png_root,
        "dds_staging_root": config.dds_staging_root,
        "output_root": config.output_root,
        "started_at": time.time(),
    }


def _is_texture_workflow_tool_log(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(
        marker in lowered
        for marker in (
            "native texture",
            "real-esrgan",
            "ncnn",
            "chainner",
            "] stage ",
            "] convert ",
            "] build ",
            "] built ",
            "timed out",
        )
    )


class ScanWorker(QObject):
    assets_ready = Signal(object)
    log_message = Signal(str)
    result_ready = Signal(int)
    error = Signal(str)
    finished = Signal()

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            self.log_message.emit("Scanning DDS files...")
            result = scan_dds_files(self.config, stop_event=self.stop_event)
            self.result_ready.emit(result.total_files)
            if not self.stop_event.is_set():
                self.assets_ready.emit(tuple(result.files))
            self.log_message.emit(f"Scan complete. Found {result.total_files} DDS files.")
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class _TextureWorkflowWorkerBase(QObject):
    log_message = Signal(str)
    phase_changed = Signal(str, str, bool)
    phase_progress_changed = Signal(int, int, str)
    total_found = Signal(int)
    current_file = Signal(str)
    progress = Signal(int, int, int, int, int)
    completed = Signal(object)
    cancelled = Signal(str)
    error = Signal(str)
    finished = Signal()

    worker_name = "TextureWorkflowWorker"
    starting_detail = "Texture workflow starting"
    cancelled_message = "Processing stopped by user."

    def __init__(
        self,
        config: AppConfig,
        *,
        crash_reports_dir: Optional[Path] = None,
        session_id: str = "",
        job_inputs=None,
    ) -> None:
        super().__init__()
        self.job_inputs = tuple(job_inputs) if job_inputs is not None else None
        self.config = config
        self.crash_reports_dir = crash_reports_dir
        self.session_id = str(session_id or "")
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    def _run_pipeline(self, **callbacks: object) -> object:
        raise NotImplementedError

    @Slot()
    def run(self) -> None:
        breadcrumb_state = _texture_workflow_breadcrumb_base(self.config, self.worker_name)
        last_breadcrumb_write = 0.0
        last_current_emit = 0.0
        last_progress_emit = 0.0
        last_phase_progress_emit = 0.0

        def write_breadcrumb(*, force: bool = False, **updates: object) -> None:
            nonlocal last_breadcrumb_write
            breadcrumb_state.update(updates)
            now = time.monotonic()
            if not force and last_breadcrumb_write != 0.0 and (now - last_breadcrumb_write) < 0.5:
                return
            last_breadcrumb_write = now
            breadcrumb_state["timestamp"] = time.time()
            _write_texture_workflow_breadcrumb(
                self.crash_reports_dir,
                self.session_id,
                breadcrumb_state,
            )

        def emit_log(message: str) -> None:
            self.log_message.emit(message)
            if _is_texture_workflow_tool_log(message):
                write_breadcrumb(force=True, last_external_tool_step=str(message))

        def emit_total(total: int) -> None:
            write_breadcrumb(force=True, total_files=total)
            self.total_found.emit(total)

        def emit_current_file(current_file: str) -> None:
            nonlocal last_current_emit
            write_breadcrumb(current_file=current_file)
            now = time.monotonic()
            if last_current_emit == 0.0 or (now - last_current_emit) >= 0.05:
                last_current_emit = now
                self.current_file.emit(current_file)

        def emit_progress(processed: int, total: int, converted: int, skipped: int, failed: int) -> None:
            nonlocal last_progress_emit
            terminal = total <= 0 or processed >= total or processed <= 1
            write_breadcrumb(
                force=terminal,
                processed=processed,
                total_files=total,
                converted=converted,
                skipped=skipped,
                failed=failed,
            )
            now = time.monotonic()
            if terminal or last_progress_emit == 0.0 or (now - last_progress_emit) >= 0.05:
                last_progress_emit = now
                self.progress.emit(processed, total, converted, skipped, failed)

        def emit_phase(phase_name: str, detail: str, indeterminate: bool) -> None:
            write_breadcrumb(force=True, phase=phase_name, phase_detail=detail, phase_indeterminate=indeterminate)
            self.phase_changed.emit(phase_name, detail, indeterminate)

        def emit_phase_progress(current: int, total: int, detail: str) -> None:
            nonlocal last_phase_progress_emit
            terminal = total <= 0 or current >= total or current <= 1
            write_breadcrumb(
                force=terminal,
                phase_current=current,
                phase_total=total,
                phase_progress_detail=detail,
            )
            now = time.monotonic()
            if terminal or last_phase_progress_emit == 0.0 or (now - last_phase_progress_emit) >= 0.05:
                last_phase_progress_emit = now
                self.phase_progress_changed.emit(current, total, detail)

        write_breadcrumb(force=True, phase="starting", phase_detail=self.starting_detail)
        try:
            summary = self._run_pipeline(
                on_log=emit_log,
                on_total=emit_total,
                on_current_file=emit_current_file,
                on_progress=emit_progress,
                on_phase=emit_phase,
                on_phase_progress=emit_phase_progress,
                stop_event=self.stop_event,
            )
            if getattr(summary, "cancelled", False):
                write_breadcrumb(force=True, status="cancelled", phase_detail=self.cancelled_message)
                self.cancelled.emit(self.cancelled_message)
            else:
                write_breadcrumb(
                    force=True,
                    status="completed",
                    total_files=getattr(summary, "total_files", 0),
                    converted=getattr(summary, "converted", 0),
                    skipped=getattr(summary, "skipped", 0),
                    failed=getattr(summary, "failed", 0),
                )
                self.completed.emit(summary)
        except Exception as exc:
            write_breadcrumb(force=True, status="error", error=str(exc))
            self.error.emit(str(exc))
        finally:
            if breadcrumb_state.get("status") == "running":
                write_breadcrumb(force=True, status="finished")
            else:
                write_breadcrumb(force=True)
            self.finished.emit()


class BuildWorker(_TextureWorkflowWorkerBase):
    worker_name = "BuildWorker"
    starting_detail = "Texture workflow build starting"
    cancelled_message = "Processing stopped by user."

    def _run_pipeline(self, **callbacks: object) -> object:
        if self.job_inputs is not None:
            from cdmw.services.texture_job_service import run_texture_job_pipeline
            return run_texture_job_pipeline(self.config, self.job_inputs, rebuild_dds_files, **callbacks)
        return rebuild_dds_files(self.config, **callbacks)


class DdsToPngWorker(_TextureWorkflowWorkerBase):
    worker_name = "DdsToPngWorker"
    starting_detail = "DDS to PNG conversion starting"
    cancelled_message = "DDS to PNG conversion stopped by user."

    def _run_pipeline(self, **callbacks: object) -> object:
        if self.job_inputs is not None:
            from cdmw.services.texture_job_service import run_texture_job_pipeline
            return run_texture_job_pipeline(self.config, self.job_inputs, convert_dds_to_pngs, **callbacks)
        return convert_dds_to_pngs(self.config, **callbacks)


__all__ = ["BuildWorker", "DdsToPngWorker", "ScanWorker"]
