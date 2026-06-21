"""Preview worker extraction point."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.core.texture_pipeline.preview import build_compare_preview_pane_result
from cdmw.models import RunCancelled


class VisualPlacementPreviewWorker(QObject):
    completed = Signal(int, object)
    error = Signal(int, str)
    finished = Signal(int)

    def __init__(self, request_id: int, task: Callable[[], object]) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.task = task

    @Slot()
    def run(self) -> None:
        try:
            self.completed.emit(self.request_id, self.task())
        except Exception as exc:
            self.error.emit(self.request_id, str(exc))
        finally:
            self.finished.emit(self.request_id)


class ComparePreviewWorker(QObject):
    completed = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        request_id: int,
        texconv_path: Optional[Path],
        original_path: Optional[Path],
        output_path: Optional[Path],
        original_planner_summary: str = "",
        output_planner_summary: str = "",
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.texconv_path = texconv_path
        self.original_path = original_path
        self.output_path = output_path
        self.original_planner_summary = original_planner_summary
        self.output_planner_summary = output_planner_summary
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            payload = {
                "original": build_compare_preview_pane_result(
                    self.texconv_path,
                    self.original_path,
                    "Original DDS not found.",
                    self.original_planner_summary,
                    stop_event=self.stop_event,
                ),
                "output": build_compare_preview_pane_result(
                    self.texconv_path,
                    self.output_path,
                    "Output DDS not found.",
                    self.output_planner_summary,
                    stop_event=self.stop_event,
                ),
            }
            if not self.stop_event.is_set():
                self.completed.emit(self.request_id, payload)
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, str(exc))
        finally:
            self.finished.emit()


class AlignmentOriginalTexturePreviewWorker(QObject):
    completed = Signal(int, object, int, float)
    error = Signal(int, str)
    finished = Signal()

    def __init__(self, request_id: int, resolver: Callable[[threading.Event], tuple[object, int]]) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.resolver = resolver
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        started = time.perf_counter()
        try:
            if self.stop_event.is_set():
                return
            preview_model, native_material_batches = self.resolver(self.stop_event)
            if not self.stop_event.is_set():
                self.completed.emit(
                    self.request_id,
                    preview_model,
                    int(native_material_batches or 0),
                    max(0.0, (time.perf_counter() - started) * 1000.0),
                )
        except RunCancelled:
            pass
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, str(exc))
        finally:
            self.finished.emit()


__all__ = [
    "AlignmentOriginalTexturePreviewWorker",
    "ComparePreviewWorker",
    "VisualPlacementPreviewWorker",
]
