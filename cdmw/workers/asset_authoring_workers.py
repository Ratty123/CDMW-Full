from __future__ import annotations

import threading
from pathlib import Path
from typing import Mapping, Sequence

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.services.asset_authoring_service import AssetAuthoringService


class MaterialMakerExportWorker(QObject):
    progress_changed = Signal(int, int, str)
    completed = Signal(object)
    cancelled = Signal(str)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        project_path: Path | str,
        output_dir: Path | str,
        *,
        configured_paths: Mapping[str, object] | None = None,
        material_name: str = "",
        channel_overrides: Mapping[str, object] | None = None,
        timeout_s: float | None = None,
        service: AssetAuthoringService | None = None,
    ) -> None:
        super().__init__()
        self.project_path = project_path
        self.output_dir = output_dir
        self.configured_paths = configured_paths
        self.material_name = material_name
        self.channel_overrides = channel_overrides
        self.timeout_s = timeout_s
        self.service = service or AssetAuthoringService()
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                self.cancelled.emit("Material Maker export stopped.")
                return
            self.progress_changed.emit(0, 2, "Running Material Maker export...")
            export_report = self.service.run_material_maker_export(
                self.project_path,
                self.output_dir,
                self.configured_paths,
                timeout_s=self.timeout_s,
            )
            if self.stop_event.is_set():
                self.cancelled.emit("Material Maker export stopped.")
                return
            texture_set_report: dict[str, object] | None = None
            if str(export_report.get("status") or "") == "ok":
                self.progress_changed.emit(1, 2, "Reviewing exported texture set...")
                texture_set_report = self.service.ingest_exported_texture_set(
                    self.output_dir,
                    material_name=self.material_name,
                    channel_overrides=self.channel_overrides,
                )
            self.progress_changed.emit(2, 2, "Material Maker export finished.")
            self.completed.emit(
                {
                    "status": export_report.get("status", "unknown"),
                    "operation": "material_maker_export",
                    "export_report": export_report,
                    "texture_set_report": texture_set_report,
                }
            )
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class OpenImageIOTaskWorker(QObject):
    completed = Signal(object)
    cancelled = Signal(str)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        operation: str,
        paths: Sequence[Path | str],
        *,
        configured_paths: Mapping[str, object] | None = None,
        timeout_s: float | None = None,
        service: AssetAuthoringService | None = None,
    ) -> None:
        super().__init__()
        self.operation = str(operation or "")
        self.paths = tuple(paths)
        self.configured_paths = configured_paths
        self.timeout_s = timeout_s
        self.service = service or AssetAuthoringService()
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                self.cancelled.emit("OpenImageIO task stopped.")
                return
            result = self._run_operation()
            if self.stop_event.is_set():
                self.cancelled.emit("OpenImageIO task stopped.")
                return
            self.completed.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()

    def _run_operation(self) -> dict[str, object]:
        if self.operation == "metadata" and len(self.paths) == 1:
            return self.service.run_openimageio_metadata(
                self.paths[0],
                self.configured_paths,
                timeout_s=self.timeout_s,
            )
        if self.operation == "convert" and len(self.paths) == 2:
            return self.service.run_openimageio_convert(
                self.paths[0],
                self.paths[1],
                self.configured_paths,
                timeout_s=self.timeout_s,
            )
        if self.operation == "diff" and len(self.paths) == 2:
            return self.service.run_openimageio_diff(
                self.paths[0],
                self.paths[1],
                self.configured_paths,
                timeout_s=self.timeout_s,
            )
        raise ValueError(f"Unsupported OpenImageIO worker operation: {self.operation}")


__all__ = ["MaterialMakerExportWorker", "OpenImageIOTaskWorker"]
