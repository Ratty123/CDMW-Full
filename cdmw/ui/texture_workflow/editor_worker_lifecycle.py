from __future__ import annotations

"""Worker shutdown lifecycle hooks for the standalone Texture Editor tab."""

from typing import Optional

from PySide6.QtCore import QThread


class TextureEditorWorkerLifecycleMixin:
    def iter_shutdown_workers(self) -> tuple[tuple[str, Optional[QThread], Optional[object]], ...]:
        return (
            ("task_thread", self._task_thread, self._task_worker),
            ("ui_constraint_thread", self._ui_constraint_thread, self._ui_constraint_worker),
        )

    def request_shutdown(self) -> None:
        if self._task_worker is not None:
            self._task_worker.stop()
        if self._task_thread is not None:
            try:
                self._task_thread.requestInterruption()
            except Exception:
                pass
            self._task_thread.quit()
        if self._ui_constraint_worker is not None:
            self._ui_constraint_worker.stop()
        if self._ui_constraint_thread is not None:
            try:
                self._ui_constraint_thread.requestInterruption()
            except Exception:
                pass
            self._ui_constraint_thread.quit()
        self.flush_settings_save()

    def shutdown(self) -> None:
        self.request_shutdown()


__all__ = ["TextureEditorWorkerLifecycleMixin"]
