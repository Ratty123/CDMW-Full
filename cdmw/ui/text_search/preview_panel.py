"""Preview loading and find-highlighting behavior for Text Search."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QThread, Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit, QTreeWidgetItem

from cdmw.core.text_search import TextSearchPreview, TextSearchResult
from cdmw.ui.text_search.workers import TextSearchPreviewWorker
from cdmw.ui.themes import get_theme


class TextSearchPreviewMixin:
    def _handle_result_selection_changed(self, current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
        if current is None:
            return
        raw = current.data(0, Qt.UserRole)
        if not isinstance(raw, int) or raw < 0 or raw >= len(self.search_results):
            return
        result = self.search_results[raw]
        self.current_preview_result = result
        self._schedule_preview(result)

    def _schedule_preview(self, result: TextSearchResult) -> None:
        self.preview_request_id += 1
        self.preview_title_label.setText(result.relative_path)
        self.preview_meta_label.setText("Loading preview...")
        self.preview_detail_label.setText("Preparing preview...")
        self.preview_text_edit.setPlainText("")
        self.preview_text_edit.set_match_selections([])
        self.preview_search_spans = []
        self.preview_find_spans = []
        self.preview_find_active_index = -1
        self.preview_text_cache = ""
        self.preview_find_status_label.setText("Loading preview...")
        if self.preview_worker is not None:
            self.preview_worker.stop()
        self.scheduled_preview_result = result
        self._preview_debounce_timer.start()

    def _flush_scheduled_preview_request(self) -> None:
        if self.scheduled_preview_result is None:
            return
        result = self.scheduled_preview_result
        self.scheduled_preview_result = None
        if self.preview_thread is not None:
            self.pending_preview_result = result
            if self.preview_worker is not None:
                self.preview_worker.stop()
            return
        request_id = self.preview_request_id + 1
        self.preview_request_id = request_id
        self._start_preview_worker(request_id, result)

    def _start_preview_worker(self, request_id: int, result: TextSearchResult) -> None:
        worker = TextSearchPreviewWorker(
            request_id=request_id,
            result=result,
            query=self.last_search_query,
            regex_enabled=self.last_search_regex_enabled,
            case_sensitive=self.last_search_case_sensitive,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_preview_ready)
        worker.error.connect(self._handle_preview_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_preview_refs)
        self.preview_worker = worker
        self.preview_thread = thread
        thread.start()

    def _handle_preview_ready(self, request_id: int, payload: object) -> None:
        if request_id != self.preview_request_id or not isinstance(payload, TextSearchPreview):
            return
        preview = payload
        self.preview_title_label.setText(preview.title)
        self.preview_meta_label.setText(preview.metadata)
        preview_detail_text = preview.detail_text
        syntax_extension = Path(preview.title).suffix.lower()
        if len(preview.preview_text) > self.SYNTAX_HIGHLIGHT_CHAR_LIMIT:
            syntax_extension = ""
            preview_detail_text = "\n".join(
                part
                for part in [
                    preview_detail_text.strip(),
                    "Syntax colors disabled for this very large preview to keep the editor responsive.",
                ]
                if part
            )
        if len(preview.preview_text) > self.PREVIEW_DISPLAY_CHAR_LIMIT:
            preview_detail_text = "\n".join(
                part
                for part in [
                    preview_detail_text.strip(),
                    (
                        f"Preview truncated to {self.PREVIEW_DISPLAY_CHAR_LIMIT:,} characters "
                        "to keep scrolling and selection responsive."
                    ),
                ]
                if part
            )
        self.preview_detail_label.setText(preview_detail_text)
        self.preview_text_edit.set_language_for_extension(syntax_extension)
        self._apply_preview_content(preview)

    def _handle_preview_error(self, request_id: int, message: str) -> None:
        if request_id != self.preview_request_id:
            return
        result = self.current_preview_result
        self.preview_title_label.setText(result.relative_path if result is not None else "Preview failed.")
        self.preview_meta_label.setText("Preview failed.")
        self.preview_detail_label.setText(message)
        self.preview_text_edit.setPlainText("")
        self.preview_text_edit.set_match_selections([])
        self.preview_search_spans = []
        self.preview_find_spans = []
        self.preview_find_active_index = -1
        self.preview_text_cache = ""
        self.preview_find_status_label.setText("Preview failed.")

    def _cleanup_preview_refs(self) -> None:
        self.preview_thread = None
        self.preview_worker = None
        if self.pending_preview_result is None:
            return
        result = self.pending_preview_result
        self.pending_preview_result = None
        request_id = self.preview_request_id + 1
        self.preview_request_id = request_id
        self._start_preview_worker(request_id, result)

    def _apply_preview_content(self, preview: TextSearchPreview) -> None:
        preview_text = preview.preview_text
        display_text = preview_text
        truncated = len(preview_text) > self.PREVIEW_DISPLAY_CHAR_LIMIT
        if truncated:
            display_text = preview_text[: self.PREVIEW_DISPLAY_CHAR_LIMIT] + "\n\n[Preview truncated for UI responsiveness.]"
        self.preview_text_edit.setPlainText(display_text)
        self.preview_text_cache = display_text
        if truncated or len(display_text) > self.MATCH_HIGHLIGHT_CHAR_LIMIT:
            self.preview_search_spans = []
        else:
            self.preview_search_spans = list(preview.match_spans)
        self.preview_find_active_index = -1
        self._handle_preview_find_changed(reset_focus=True)
        if not self.preview_find_spans and self.preview_search_spans:
            first_start, first_end = self.preview_search_spans[0]
            self.preview_text_edit.center_on_span(first_start, first_end)
        elif not self.preview_search_spans:
            self.preview_text_edit.moveCursor(QTextCursor.Start)
            self.preview_text_edit.verticalScrollBar().setValue(0)
            self.preview_text_edit.horizontalScrollBar().setValue(0)

    def _adjust_preview_font(self, delta: int) -> None:
        new_size = self.preview_text_edit.adjust_font_size(delta)
        self.preview_find_status_label.setText(
            f"{self._preview_match_status_text()} | Font {new_size} pt"
            if self.preview_text_cache
            else f"Font {new_size} pt"
        )
        self.schedule_settings_save()

    def _handle_preview_wrap_changed(self, enabled: bool) -> None:
        self.preview_text_edit.set_wrap_enabled(enabled)
        self.schedule_settings_save()

    def _handle_preview_find_changed(self, _text: str = "", *, reset_focus: bool = True) -> None:
        query = self.preview_find_edit.text()
        self.preview_find_spans = self._find_preview_spans(query, self.preview_find_case_checkbox.isChecked())
        self.preview_find_active_index = 0 if self.preview_find_spans else -1
        self._refresh_preview_selections(focus_current=bool(self.preview_find_spans and reset_focus))
        self._update_preview_find_status()
        self._update_controls()

    def _find_preview_spans(self, query: str, case_sensitive: bool) -> List[tuple[int, int]]:
        query = query or ""
        if not query or not self.preview_text_cache:
            return []
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(re.escape(query), flags)
        return [
            match.span()
            for match in pattern.finditer(self.preview_text_cache)
            if match.end() > match.start()
        ]

    def _make_selection(self, start: int, end: int, fmt: QTextCharFormat) -> QTextEdit.ExtraSelection:
        cursor = QTextCursor(self.preview_text_edit.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        selection.format = fmt
        return selection

    def _refresh_preview_selections(self, *, focus_current: bool) -> None:
        selections: List[QTextEdit.ExtraSelection] = []
        theme = get_theme(self.current_theme_key)
        search_format = QTextCharFormat()
        search_bg = QColor("#e3b341" if QColor(theme["window"]).lightnessF() < 0.55 else "#ffd866")
        search_bg.setAlpha(185)
        search_format.setBackground(search_bg)
        search_format.setForeground(QColor("#111111"))
        search_format.setFontWeight(QFont.DemiBold)

        find_format = QTextCharFormat()
        find_bg = QColor(theme["accent_soft"])
        if find_bg.alpha() == 255:
            find_bg.setAlpha(210)
        find_format.setBackground(find_bg)
        find_format.setForeground(QColor(theme["text_strong"]))

        active_find_format = QTextCharFormat()
        active_find_format.setBackground(QColor(theme["accent"]))
        active_find_format.setForeground(QColor("#ffffff"))
        active_find_format.setFontWeight(QFont.Bold)

        for start, end in self.preview_search_spans:
            if end > start:
                selections.append(self._make_selection(start, end, search_format))

        active_span: Optional[tuple[int, int]] = None
        for index, (start, end) in enumerate(self.preview_find_spans):
            if end <= start:
                continue
            if index == self.preview_find_active_index:
                active_span = (start, end)
                selections.append(self._make_selection(start, end, active_find_format))
            else:
                selections.append(self._make_selection(start, end, find_format))

        self.preview_text_edit.set_match_selections(selections)
        if focus_current and active_span is not None:
            self.preview_text_edit.center_on_span(*active_span)

    def _preview_match_status_text(self) -> str:
        if not self.preview_text_cache:
            return "No preview loaded."
        if self.preview_find_spans:
            return f"Find matches: {self.preview_find_active_index + 1} / {len(self.preview_find_spans):,}"
        if self.preview_search_spans:
            return f"Search highlights: {len(self.preview_search_spans):,}"
        return "No highlighted matches."

    def _update_preview_find_status(self) -> None:
        self.preview_find_status_label.setText(self._preview_match_status_text())

    def _jump_to_preview_find_match(self, direction: int) -> None:
        if not self.preview_find_spans:
            return
        self.preview_find_active_index = (self.preview_find_active_index + direction) % len(self.preview_find_spans)
        self._refresh_preview_selections(focus_current=True)
        self._update_preview_find_status()

    def _jump_to_previous_preview_find_match(self) -> None:
        self._jump_to_preview_find_match(-1)

    def _jump_to_next_preview_find_match(self) -> None:
        self._jump_to_preview_find_match(1)


__all__ = ["TextSearchPreviewMixin"]
