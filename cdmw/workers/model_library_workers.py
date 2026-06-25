"""Qt workers for Model Library background tasks."""

from __future__ import annotations

import shutil
import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot


class ModelLibraryTaskWorker(QObject):
    completed = Signal(object)
    error = Signal(str)
    finished = Signal()
    progress = Signal(str)

    def __init__(self, task: Callable[[Callable[[str], None]], object]) -> None:
        super().__init__()
        self.task = task

    @Slot()
    def run(self) -> None:
        try:
            self.completed.emit(self.task(lambda message: self.progress.emit(str(message))))
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


def _remove_model_library_preview_package_dir(package_dir: Path) -> None:
    try:
        shutil.rmtree(package_dir, ignore_errors=True)
    except OSError:
        pass


def remove_model_library_preview_package_dir(package_dir: Path | str | None) -> threading.Thread | None:
    if package_dir is None:
        return None
    path = Path(package_dir)
    if not path.name.startswith("cdmw_isolated_d3d11_"):
        return None
    thread = threading.Thread(
        target=_remove_model_library_preview_package_dir,
        args=(path,),
        name="cdmw-model-library-preview-cleanup",
        daemon=True,
    )
    thread.start()
    return thread


__all__ = ["ModelLibraryTaskWorker", "remove_model_library_preview_package_dir"]
