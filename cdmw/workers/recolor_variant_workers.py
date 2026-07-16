"""Cancellable worker for Recolor analysis and preview operations."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.models import RunCancelled
from cdmw.core.recolor_variants import (
    RecolorVariantAnalysis,
    RecolorVariantOutputProfile,
    RecolorVariantTemplate,
    build_recolor_variant_outputs,
)


class RecolorVariantBuildWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)
    log_message = Signal(str)
    progress_changed = Signal(int, int, str)
    finished = Signal()

    def __init__(
        self,
        analysis: RecolorVariantAnalysis,
        template: RecolorVariantTemplate,
        output_root: Path,
        profiles: Sequence[RecolorVariantOutputProfile],
        *,
        overwrite_existing: bool,
    ) -> None:
        super().__init__()
        self.analysis = analysis
        self.template = template
        self.output_root = output_root
        self.profiles = tuple(profiles)
        self.overwrite_existing = bool(overwrite_existing)
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            result = build_recolor_variant_outputs(
                self.analysis,
                self.template,
                self.output_root,
                self.profiles,
                overwrite_existing=self.overwrite_existing,
                stop_event=self.stop_event,
                on_log=lambda message: _emit(self.log_message, message),
                on_progress=lambda current, total, label: _emit(
                    self.progress_changed,
                    current,
                    total,
                    label,
                ),
            )
            _emit(self.completed, result)
        except RunCancelled:
            _emit(self.failed, "Recolor variant build cancelled.")
        except Exception as exc:
            _emit(self.failed, str(exc))
        finally:
            _emit(self.finished)


class RecolorVariantOperationWorker(QObject):
    completed = Signal(int, object)
    failed = Signal(int, str)
    finished = Signal()

    def __init__(self, request_id: int, task: Callable[[threading.Event], object]) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.task = task
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            _emit(self.completed, self.request_id, self.task(self.stop_event))
        except RunCancelled:
            _emit(self.failed, self.request_id, "Recolor operation cancelled.")
        except Exception as exc:
            _emit(self.failed, self.request_id, str(exc))
        finally:
            _emit(self.finished)


def _emit(signal: object, *args: object) -> None:
    try:
        signal.emit(*args)
    except RuntimeError:
        pass


__all__ = ["RecolorVariantBuildWorker", "RecolorVariantOperationWorker"]
