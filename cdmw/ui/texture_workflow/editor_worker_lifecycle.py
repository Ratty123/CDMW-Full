from __future__ import annotations

"""Worker shutdown lifecycle hooks for the standalone Texture Editor tab."""

from typing import Optional

from PySide6.QtCore import QThread


def _record_texture_worker_lifecycle(target: object, event: str, **fields: object) -> None:
    recorder = getattr(target, "_record_runtime_event", None)
    if callable(recorder):
        try:
            recorder(str(event), **fields)
        except Exception:
            return


class TextureEditorWorkerLifecycleMixin:
    def iter_shutdown_workers(self) -> tuple[tuple[str, Optional[QThread], Optional[object]], ...]:
        return (
            ("task_thread", self._task_thread, self._task_worker),
            ("ui_constraint_thread", self._ui_constraint_thread, self._ui_constraint_worker),
        )

    def request_shutdown(self) -> None:
        if self._task_worker is not None:
            _record_texture_worker_lifecycle(self, "texture_editor_worker_cancelled", reason="cancelled_by_shutdown", worker="task")
            self._task_worker.stop()
        if self._task_thread is not None:
            try:
                self._task_thread.requestInterruption()
            except Exception as exc:
                _record_texture_worker_lifecycle(self, "texture_editor_worker_failed", reason="worker_failed", worker="task", error=str(exc))
            self._task_thread.quit()
        if self._ui_constraint_worker is not None:
            _record_texture_worker_lifecycle(self, "texture_editor_worker_cancelled", reason="cancelled_by_shutdown", worker="ui_constraint")
            self._ui_constraint_worker.stop()
        if self._ui_constraint_thread is not None:
            try:
                self._ui_constraint_thread.requestInterruption()
            except Exception as exc:
                _record_texture_worker_lifecycle(self, "texture_editor_worker_failed", reason="worker_failed", worker="ui_constraint", error=str(exc))
            self._ui_constraint_thread.quit()
        self.flush_settings_save()

    def shutdown(self) -> None:
        self.request_shutdown()


__all__ = ["TextureEditorWorkerLifecycleMixin"]
