from __future__ import annotations

"""Status, sidebar scroll, and cache invalidation helpers for Texture Editor UI."""

from typing import Callable, Optional, Tuple

from PySide6.QtCore import QTimer

from cdmw.ui.texture_workflow.editor_layer_state import texture_editor_layer_thumbnail_cache_keys
from cdmw.ui.texture_workflow.editor_view_state import merged_texture_editor_composite_dirty_bounds


class TextureEditorStatusCacheUiMixin:
    def _restore_left_sidebar_scroll(self, scroll_x: int, scroll_y: int) -> None:
        if self.left_scroll is None:
            return
        hbar = self.left_scroll.horizontalScrollBar()
        vbar = self.left_scroll.verticalScrollBar()
        hbar.setValue(max(hbar.minimum(), min(hbar.maximum(), int(scroll_x))))
        vbar.setValue(max(vbar.minimum(), min(vbar.maximum(), int(scroll_y))))

    def _capture_left_sidebar_scroll(self) -> Tuple[int, int]:
        if self.left_scroll is None:
            return (0, 0)
        return (
            int(self.left_scroll.horizontalScrollBar().value()),
            int(self.left_scroll.verticalScrollBar().value()),
        )

    def _schedule_left_sidebar_scroll_restore(self, scroll_x: int, scroll_y: int) -> None:
        QTimer.singleShot(0, lambda sx=scroll_x, sy=scroll_y: self._restore_left_sidebar_scroll(sx, sy))

    def _set_status(self, message: str, error: bool) -> None:
        sidebar_scroll = self._capture_left_sidebar_scroll()
        source_message = str(message or "")
        translated_message = self._translate_ui_text(source_message)
        self.status_label.setProperty("_i18n_source_text", source_message)
        self.status_label.setText(translated_message)
        self._schedule_left_sidebar_scroll_restore(*sidebar_scroll)
        self.status_message_requested.emit(translated_message, error)

    def set_ui_translator(self, translator: Callable[[str], str]) -> None:
        self._translate_ui_text = translator if callable(translator) else (lambda text: str(text or ""))
        source_message = self.status_label.property("_i18n_source_text")
        if isinstance(source_message, str) and source_message:
            self.status_label.setText(self._translate_ui_text(source_message))

    def _invalidate_composite_cache(self, dirty_bounds: Optional[Tuple[int, int, int, int]] = None) -> None:
        self._composite_cache_revision = -1
        if dirty_bounds is None:
            self._composite_dirty_bounds = None
            self._composite_cache = None
            return
        self._composite_dirty_bounds = merged_texture_editor_composite_dirty_bounds(
            self._composite_dirty_bounds,
            dirty_bounds,
        )

    def _invalidate_layer_thumbnail(self, layer_id: str) -> None:
        for key in texture_editor_layer_thumbnail_cache_keys(layer_id, self._thumbnail_cache.keys()):
            self._thumbnail_cache.pop(key, None)

    def _busy(self) -> bool:
        return self._task_thread is not None


__all__ = ["TextureEditorStatusCacheUiMixin"]
