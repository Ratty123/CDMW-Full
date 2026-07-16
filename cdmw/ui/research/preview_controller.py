from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread

from cdmw.models import ArchiveEntry, ArchivePreviewResult
from cdmw.ui.research.display_preferences_state import clamp_preview_zoom_factor
from cdmw.ui.research.preview_controls import (
    apply_preview_zoom,
    next_manual_preview_zoom,
    set_preview_image_controls_enabled,
    set_preview_zoom_label,
)
from cdmw.ui.research.preview_state import (
    archive_picker_clear_preview_state,
    archive_picker_folder_preview_state,
    archive_picker_loading_preview_state,
    research_preview_display_state,
    unknown_clear_preview_state,
    unknown_loading_preview_state,
)
from cdmw.ui.research.workers import UnknownResolverPreviewWorker

def _set_archive_picker_preview_image_controls_enabled(self, enabled: bool) -> None:
    set_preview_image_controls_enabled(
        enabled,
        buttons=(self.archive_picker_preview_zoom_out_button, self.archive_picker_preview_zoom_fit_button, self.archive_picker_preview_zoom_100_button, self.archive_picker_preview_zoom_in_button),
        zoom_value_label=self.archive_picker_preview_zoom_value,
        refresh_label=self._update_archive_picker_preview_zoom_label,
    )

def _update_archive_picker_preview_zoom_label(self) -> None:
    set_preview_zoom_label(
        self.archive_picker_preview_zoom_value,
        fit_to_view=self.archive_picker_preview_fit_to_view,
        zoom_factor=self.archive_picker_preview_zoom_factor,
    )

def _apply_archive_picker_preview_zoom(self) -> None:
    apply_preview_zoom(self.archive_picker_preview_label, self.archive_picker_preview_zoom_value, fit_to_view=self.archive_picker_preview_fit_to_view, zoom_factor=self.archive_picker_preview_zoom_factor)

def _set_archive_picker_preview_fit_mode(self) -> None:
    self.archive_picker_preview_fit_to_view = True
    self._apply_archive_picker_preview_zoom()

def _set_archive_picker_preview_zoom_factor(self, zoom_factor: float) -> None:
    self.archive_picker_preview_fit_to_view = False
    self.archive_picker_preview_zoom_factor = clamp_preview_zoom_factor(zoom_factor)
    self._apply_archive_picker_preview_zoom()

def _adjust_archive_picker_preview_zoom(self, step: int) -> None:
    self._set_archive_picker_preview_zoom_factor(
        next_manual_preview_zoom(
            current_display_scale=self.archive_picker_preview_label.current_display_scale(),
            fit_to_view=self.archive_picker_preview_fit_to_view,
            zoom_factor=self.archive_picker_preview_zoom_factor,
            step=step,
        )
    )

def _clear_archive_picker_preview(self, message: str) -> None:
    text_state = archive_picker_clear_preview_state(message)
    self.archive_picker_preview_request_id += 1
    self.pending_archive_picker_preview_request = None
    self.archive_picker_preview_title_label.setText(text_state.title)
    self.archive_picker_preview_meta_label.setText(text_state.metadata_text)
    self.archive_picker_preview_warning_label.clear()
    self.archive_picker_preview_warning_label.setVisible(False)
    self.archive_picker_preview_info_edit.setPlainText(text_state.info_text)
    self.archive_picker_preview_text_edit.clear()
    self.archive_picker_preview_details_edit.clear()
    self.archive_picker_preview_label.clear_preview(text_state.image_empty_text)
    self.archive_picker_preview_stack.setCurrentWidget(self.archive_picker_preview_info_edit)
    self.archive_picker_preview_tabs.setCurrentIndex(0)
    self._set_archive_picker_preview_image_controls_enabled(False)

def _show_archive_picker_folder_preview(self, folder_text: str, count: int) -> None:
    text_state = archive_picker_folder_preview_state(folder_text, count)
    self.archive_picker_preview_title_label.setText(text_state.title)
    self.archive_picker_preview_meta_label.setText(text_state.metadata_text)
    self.archive_picker_preview_warning_label.clear()
    self.archive_picker_preview_warning_label.setVisible(False)
    self.archive_picker_preview_info_edit.setPlainText(text_state.info_text)
    self.archive_picker_preview_details_edit.setPlainText(text_state.details_text)
    self.archive_picker_preview_label.clear_preview(text_state.image_empty_text)
    self.archive_picker_preview_stack.setCurrentWidget(self.archive_picker_preview_info_edit)
    self.archive_picker_preview_tabs.setCurrentIndex(0)
    self._set_archive_picker_preview_image_controls_enabled(False)

def _render_archive_picker_preview_for_entry(self, entry: Optional[ArchiveEntry]) -> None:
    request_id = self.archive_picker_preview_request_id + 1
    self.archive_picker_preview_request_id = request_id
    if entry is None:
        self.pending_archive_picker_preview_request = None
        self._clear_archive_picker_preview("Select a file in Archive Files to preview it here.")
        return

    text_state = archive_picker_loading_preview_state(entry.basename)
    self.archive_picker_preview_title_label.setText(text_state.title)
    self.archive_picker_preview_meta_label.setText(text_state.metadata_text)
    self.archive_picker_preview_warning_label.clear()
    self.archive_picker_preview_warning_label.setVisible(False)
    self.archive_picker_preview_info_edit.setPlainText(text_state.info_text)
    self.archive_picker_preview_details_edit.setPlainText(text_state.details_text)
    self.archive_picker_preview_stack.setCurrentWidget(self.archive_picker_preview_info_edit)
    self.pending_archive_picker_preview_request = None

    if self.archive_picker_preview_thread is not None:
        self.pending_archive_picker_preview_request = (request_id, entry)
        if self.archive_picker_preview_worker is not None:
            self.archive_picker_preview_worker.stop()
        return
    self._start_archive_picker_preview_worker(request_id, entry)

def _start_archive_picker_preview_worker(
    self,
    request_id: int,
    entry: Optional[ArchiveEntry],
) -> None:
    worker = UnknownResolverPreviewWorker(request_id, entry)
    thread = QThread(self)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.completed.connect(self._handle_archive_picker_preview_ready)
    worker.error.connect(self._handle_archive_picker_preview_error)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(self._cleanup_archive_picker_preview_refs)
    self.archive_picker_preview_worker = worker
    self.archive_picker_preview_thread = thread
    thread.start()

def _handle_archive_picker_preview_ready(self, request_id: int, payload: object) -> None:
    if request_id != self.archive_picker_preview_request_id:
        return
    if isinstance(payload, ArchivePreviewResult):
        self._apply_archive_picker_preview_result(payload)

def _handle_archive_picker_preview_error(self, request_id: int, message: str) -> None:
    if request_id != self.archive_picker_preview_request_id:
        return
    self._clear_archive_picker_preview(f"Preview failed: {message}")

def _cleanup_archive_picker_preview_refs(self) -> None:
    self.archive_picker_preview_worker = None
    self.archive_picker_preview_thread = None
    if self.pending_archive_picker_preview_request is None:
        return
    request_id, entry = self.pending_archive_picker_preview_request
    self.pending_archive_picker_preview_request = None
    self.archive_picker_preview_request_id = request_id
    self._start_archive_picker_preview_worker(request_id, entry)

def _apply_archive_picker_preview_result(self, result: ArchivePreviewResult) -> None:
    display = research_preview_display_state(result)
    self.archive_picker_preview_title_label.setText(display.title)
    self.archive_picker_preview_meta_label.setText(display.metadata_summary)
    self.archive_picker_preview_warning_label.setText(display.warning_text)
    self.archive_picker_preview_warning_label.setVisible(bool(display.warning_text))
    self.archive_picker_preview_info_edit.setPlainText(display.detail_text)
    self.archive_picker_preview_details_edit.setPlainText(display.detail_text)
    if display.use_image_view:
        if result.preview_image is not None:
            self.archive_picker_preview_label.set_preview_image(result.preview_image, display.image_title)
        else:
            self.archive_picker_preview_label.set_preview_image_path(
                result.preview_image_path, display.image_title
            )
        self.archive_picker_preview_stack.setCurrentWidget(self.archive_picker_preview_scroll)
        self.archive_picker_preview_tabs.setCurrentIndex(0)
        self._set_archive_picker_preview_image_controls_enabled(True)
        self._apply_archive_picker_preview_zoom()
        return
    if display.use_text_view:
        self.archive_picker_preview_text_edit.setPlainText(display.preview_text)
        self.archive_picker_preview_stack.setCurrentWidget(self.archive_picker_preview_text_edit)
        self.archive_picker_preview_tabs.setCurrentIndex(0)
        self.archive_picker_preview_label.clear_preview("No image preview available.")
        self._set_archive_picker_preview_image_controls_enabled(False)
        return
    self.archive_picker_preview_label.clear_preview("No image preview available.")
    self.archive_picker_preview_stack.setCurrentWidget(self.archive_picker_preview_info_edit)
    self.archive_picker_preview_tabs.setCurrentIndex(0)
    self._set_archive_picker_preview_image_controls_enabled(False)

def _set_unknown_preview_image_controls_enabled(self, enabled: bool) -> None:
    set_preview_image_controls_enabled(
        enabled,
        buttons=(self.unknown_preview_zoom_out_button, self.unknown_preview_zoom_fit_button, self.unknown_preview_zoom_100_button, self.unknown_preview_zoom_in_button),
        zoom_value_label=self.unknown_preview_zoom_value,
        refresh_label=self._update_unknown_preview_zoom_label,
    )

def _update_unknown_preview_zoom_label(self) -> None:
    set_preview_zoom_label(
        self.unknown_preview_zoom_value,
        fit_to_view=self.unknown_preview_fit_to_view,
        zoom_factor=self.unknown_preview_zoom_factor,
    )

def _apply_unknown_preview_zoom(self) -> None:
    apply_preview_zoom(self.unknown_preview_label, self.unknown_preview_zoom_value, fit_to_view=self.unknown_preview_fit_to_view, zoom_factor=self.unknown_preview_zoom_factor)

def _set_unknown_preview_fit_mode(self) -> None:
    self.unknown_preview_fit_to_view = True
    self._apply_unknown_preview_zoom()

def _set_unknown_preview_zoom_factor(self, zoom_factor: float) -> None:
    self.unknown_preview_fit_to_view = False
    self.unknown_preview_zoom_factor = clamp_preview_zoom_factor(zoom_factor)
    self._apply_unknown_preview_zoom()

def _adjust_unknown_preview_zoom(self, step: int) -> None:
    self._set_unknown_preview_zoom_factor(
        next_manual_preview_zoom(
            current_display_scale=self.unknown_preview_label.current_display_scale(),
            fit_to_view=self.unknown_preview_fit_to_view,
            zoom_factor=self.unknown_preview_zoom_factor,
            step=step,
        )
    )

def _clear_unknown_preview(self, message: str) -> None:
    text_state = unknown_clear_preview_state(message)
    self.unknown_preview_title_label.setText(text_state.title)
    self.unknown_preview_meta_label.setText(text_state.metadata_text)
    self.unknown_preview_warning_label.clear()
    self.unknown_preview_warning_label.setVisible(False)
    self.unknown_preview_info_edit.setPlainText(text_state.info_text)
    self.unknown_preview_label.clear_preview(text_state.image_empty_text)
    self.unknown_preview_stack.setCurrentWidget(self.unknown_preview_info_edit)
    self._set_unknown_preview_image_controls_enabled(False)

def _render_unknown_preview_for_member(self, member: Optional[UnknownResolverMember]) -> None:
    self._ensure_archive_picker_ready()
    entry = (
        self._archive_picker_entry_for_path(member.path)
        if member is not None
        else None
    )
    request_id = self.unknown_preview_request_id + 1
    self.unknown_preview_request_id = request_id
    if entry is None:
        self.pending_unknown_preview_request = None
        self._clear_unknown_preview("No archive preview is available for the selected item in the current archive view.")
        return

    text_state = unknown_loading_preview_state(entry.basename)
    self.unknown_preview_title_label.setText(text_state.title)
    self.unknown_preview_meta_label.setText(text_state.metadata_text)
    self.unknown_preview_warning_label.setVisible(False)
    self.unknown_preview_warning_label.clear()
    self.unknown_preview_info_edit.setPlainText(text_state.info_text)
    self.unknown_preview_stack.setCurrentWidget(self.unknown_preview_info_edit)
    self.pending_unknown_preview_request = None

    if self.unknown_preview_thread is not None:
        self.pending_unknown_preview_request = (request_id, entry)
        if self.unknown_preview_worker is not None:
            self.unknown_preview_worker.stop()
        return
    self._start_unknown_preview_worker(request_id, entry)

def _start_unknown_preview_worker(
    self,
    request_id: int,
    entry: Optional[ArchiveEntry],
) -> None:
    worker = UnknownResolverPreviewWorker(request_id, entry)
    thread = QThread(self)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.completed.connect(self._handle_unknown_preview_ready)
    worker.error.connect(self._handle_unknown_preview_error)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(self._cleanup_unknown_preview_refs)
    self.unknown_preview_worker = worker
    self.unknown_preview_thread = thread
    thread.start()

def _handle_unknown_preview_ready(self, request_id: int, payload: object) -> None:
    if request_id != self.unknown_preview_request_id:
        return
    if isinstance(payload, ArchivePreviewResult):
        self._apply_unknown_preview_result(payload)

def _handle_unknown_preview_error(self, request_id: int, message: str) -> None:
    if request_id != self.unknown_preview_request_id:
        return
    self._clear_unknown_preview(f"Preview failed: {message}")

def _cleanup_unknown_preview_refs(self) -> None:
    self.unknown_preview_worker = None
    self.unknown_preview_thread = None
    if self.pending_unknown_preview_request is None:
        return
    request_id, entry = self.pending_unknown_preview_request
    self.pending_unknown_preview_request = None
    self.unknown_preview_request_id = request_id
    self._start_unknown_preview_worker(request_id, entry)

def _apply_unknown_preview_result(self, result: ArchivePreviewResult) -> None:
    display = research_preview_display_state(result)
    self.unknown_preview_title_label.setText(display.title)
    self.unknown_preview_meta_label.setText(display.metadata_summary)
    self.unknown_preview_warning_label.setText(display.warning_text)
    self.unknown_preview_warning_label.setVisible(bool(display.warning_text))
    self.unknown_preview_info_edit.setPlainText(display.detail_text)
    if display.use_image_view:
        if result.preview_image is not None:
            self.unknown_preview_label.set_preview_image(result.preview_image, display.image_title)
        else:
            self.unknown_preview_label.set_preview_image_path(result.preview_image_path, display.image_title)
        self.unknown_preview_stack.setCurrentWidget(self.unknown_preview_scroll)
        self._set_unknown_preview_image_controls_enabled(True)
        self._apply_unknown_preview_zoom()
        return
    if display.use_text_view:
        self.unknown_preview_info_edit.setPlainText(display.preview_text)
    self.unknown_preview_label.clear_preview("No image preview available.")
    self.unknown_preview_stack.setCurrentWidget(self.unknown_preview_info_edit)
    self._set_unknown_preview_image_controls_enabled(False)
