"""Texture workflow compare preview helpers."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QLabel, QListWidgetItem

from cdmw.services.texture_workflow_service import build_single_texture_processing_plan
from cdmw.services.preview_workflow_service import collect_compare_relative_paths
from cdmw.services.texture_workflow_service import normalize_config_for_planning
from cdmw.models import ComparePreviewPaneResult
from cdmw.ui.widgets import PreviewLabel
from cdmw.workers.preview_workers import ComparePreviewWorker


class TextureWorkflowComparePreviewMixin:
    """Compare-list navigation, zoom, and deferred preview workers."""
    def _get_compare_zoom_state(self, side: str) -> Tuple[PreviewLabel, bool, float, QLabel]:
        if side == "original":
            return (
                self.original_preview_label,
                self.original_compare_fit_to_view,
                self.original_compare_zoom_factor,
                self.original_compare_zoom_value,
            )
        if side == "output":
            return (
                self.output_preview_label,
                self.output_compare_fit_to_view,
                self.output_compare_zoom_factor,
                self.output_compare_zoom_value,
            )
        raise ValueError(f"Unknown compare side: {side}")

    def _update_compare_zoom_label(self, side: str) -> None:
        _label, fit_to_view, zoom_factor, value_label = self._get_compare_zoom_state(side)
        if fit_to_view:
            if abs(self.compare_preview_fit_scale - 1.0) < 0.01:
                value_label.setText("Fit")
            else:
                value_label.setText(f"Fit {int(round(self.compare_preview_fit_scale * 100))}%")
        else:
            value_label.setText(f"{int(round(zoom_factor * 100))}%")

    def _apply_compare_zoom(self, side: str) -> None:
        preview_label, fit_to_view, zoom_factor, _value_label = self._get_compare_zoom_state(side)
        preview_label.set_fit_scale(self.compare_preview_fit_scale)
        preview_label.set_fit_to_view(fit_to_view)
        preview_label.set_zoom_factor(zoom_factor)
        self._update_compare_zoom_label(side)

    def _parse_compare_preview_size_mode(self) -> float:
        raw_value = self._combo_value(self.compare_preview_size_combo).strip()
        if raw_value.startswith("fit:"):
            try:
                return max(0.5, min(4.0, float(raw_value.split(":", 1)[1])))
            except ValueError:
                return 1.25
        return 1.25

    def _apply_compare_preview_size_mode(self, *_args) -> None:
        self.compare_preview_fit_scale = self._parse_compare_preview_size_mode()
        self.original_compare_fit_to_view = True
        self.output_compare_fit_to_view = True
        self._apply_compare_zoom("original")
        self._apply_compare_zoom("output")
        self._sync_compare_scroll_positions()

    def _set_compare_fit_mode(self, side: str) -> None:
        if side == "original":
            self.original_compare_fit_to_view = True
        else:
            self.output_compare_fit_to_view = True
        self._apply_compare_zoom(side)

    def _set_compare_zoom_factor(self, side: str, zoom_factor: float) -> None:
        bounded_zoom = max(0.25, min(8.0, zoom_factor))
        if side == "original":
            self.original_compare_fit_to_view = False
            self.original_compare_zoom_factor = bounded_zoom
        else:
            self.output_compare_fit_to_view = False
            self.output_compare_zoom_factor = bounded_zoom
        self._apply_compare_zoom(side)

    def _adjust_compare_zoom(self, side: str, step: int) -> None:
        preview_label, fit_to_view, zoom_factor, _value_label = self._get_compare_zoom_state(side)
        current = zoom_factor if not fit_to_view else preview_label.current_display_scale()
        if step > 0:
            new_zoom = current * 1.25
        else:
            new_zoom = current / 1.25
        self._set_compare_zoom_factor(side, new_zoom)

    def _select_compare_offset(self, offset: int) -> None:
        count = self.compare_list.count()
        if count == 0:
            return
        current_row = self.compare_list.currentRow()
        if current_row < 0:
            current_row = 0
        next_row = max(0, min(count - 1, current_row + offset))
        self.compare_list.setCurrentRow(next_row)

    def _update_compare_navigation_state(self) -> None:
        count = self.compare_list.count()
        current_row = self.compare_list.currentRow()
        self.compare_previous_button.setEnabled(count > 0 and current_row > 0)
        self.compare_next_button.setEnabled(count > 0 and 0 <= current_row < count - 1)
        self.compare_mip_details_button.setEnabled(count > 0 and 0 <= current_row < count)
        self.compare_open_in_editor_button.setEnabled(count > 0 and 0 <= current_row < count)

    def _open_compare_in_texture_analysis(self) -> None:
        relative_path = self.current_compare_path_for_research().strip()
        if not relative_path:
            self.set_status_message("Select a DDS file in Compare first.", error=True)
            return
        self._activate_tool_widget(self.research_tab)
        self.research_tab.focus_texture_analysis_for_compare_path(relative_path, refresh_snapshot=True)

    def _sync_compare_scrollbar(self, source_bar, target_bar, value: int) -> None:
        del source_bar
        if not self.compare_sync_pan_checkbox.isChecked() or self.compare_syncing_scrollbars:
            return
        self.compare_syncing_scrollbars = True
        try:
            target_bar.setValue(value)
        finally:
            self.compare_syncing_scrollbars = False

    def _sync_compare_scroll_positions(self) -> None:
        if not self.compare_sync_pan_checkbox.isChecked():
            return
        self._sync_compare_scrollbar(
            self.original_preview_scroll.horizontalScrollBar(),
            self.output_preview_scroll.horizontalScrollBar(),
            self.original_preview_scroll.horizontalScrollBar().value(),
        )
        self._sync_compare_scrollbar(
            self.original_preview_scroll.verticalScrollBar(),
            self.output_preview_scroll.verticalScrollBar(),
            self.original_preview_scroll.verticalScrollBar().value(),
        )

    def refresh_compare_list(self, select_current: bool = False) -> None:
        original_root_text = self.original_dds_edit.text().strip()
        output_root_text = self.output_root_edit.text().strip()
        selected_text = None
        if select_current and self.compare_list.currentItem() is not None:
            selected_text = self.compare_list.currentItem().data(Qt.UserRole)
        self.compare_list.clear()
        self.compare_relative_paths = []

        if not original_root_text and not output_root_text:
            self.compare_preview_request_id += 1
            self.original_preview_meta_label.setText("")
            self.output_preview_meta_label.setText("")
            self.original_preview_label.clear_preview("Set the original and output folders to enable compare mode.")
            self.output_preview_label.clear_preview("Set the original and output folders to enable compare mode.")
            self._update_compare_navigation_state()
            return

        original_root = Path(original_root_text).expanduser()
        output_root = Path(output_root_text).expanduser()
        self.compare_relative_paths = collect_compare_relative_paths(original_root, output_root)

        for relative_path in self.compare_relative_paths:
            item = QListWidgetItem(relative_path.as_posix())
            item.setData(Qt.UserRole, str(relative_path))
            self.compare_list.addItem(item)

        if not self.compare_relative_paths:
            self.compare_preview_request_id += 1
            self.original_preview_meta_label.setText("")
            self.output_preview_meta_label.setText("")
            self.original_preview_label.clear_preview("No DDS files found to compare.")
            self.output_preview_label.clear_preview("No DDS files found to compare.")
            self._update_compare_navigation_state()
            return

        if selected_text is not None:
            for row in range(self.compare_list.count()):
                item = self.compare_list.item(row)
                if item.data(Qt.UserRole) == selected_text:
                    self.compare_list.setCurrentItem(item)
                    self._update_compare_navigation_state()
                    return

        if self._startup_benchmark_enabled():
            self.compare_list.setCurrentRow(-1)
            self._update_compare_navigation_state()
            return
        self.compare_list.setCurrentRow(0)
        self._update_compare_navigation_state()

    def _handle_compare_selection_change(
        self,
        current: Optional[QListWidgetItem],
        previous: Optional[QListWidgetItem],
    ) -> None:
        del previous
        self._update_compare_navigation_state()
        if current is None:
            self._compare_preview_timer.stop()
            self.pending_compare_preview_selection = None
            self.compare_preview_request_id += 1
            self.original_preview_meta_label.setText("")
            self.output_preview_meta_label.setText("")
            self.original_preview_label.clear_preview("Select a DDS file to preview.")
            self.output_preview_label.clear_preview("Select a DDS file to preview.")
            return

        relative_path = Path(current.data(Qt.UserRole))
        self.pending_compare_preview_selection = relative_path
        if self._compare_preview_can_autostart():
            self._compare_preview_timer.start()
        else:
            self._compare_preview_timer.stop()

    def _flush_pending_compare_preview_selection(self) -> None:
        if self._shutting_down:
            self.pending_compare_preview_selection = None
            return
        if not self._compare_preview_can_autostart():
            return
        relative_path = self.pending_compare_preview_selection
        self.pending_compare_preview_selection = None
        if relative_path is None:
            return
        self._render_compare_preview(relative_path)

    def current_compare_path_for_research(self) -> str:
        current_item = self.compare_list.currentItem()
        if current_item is None:
            return ""
        raw = current_item.data(Qt.UserRole)
        return str(raw) if raw else ""

    def _summarize_compare_planner(self, relative_path: Path) -> Tuple[str, str]:
        try:
            normalized = normalize_config_for_planning(self.collect_config())
        except Exception:
            return "", ""
        ui_warning = ""
        try:
            target_key = relative_path.as_posix().replace("\\", "/").strip("/").casefold()
            ui_rows = self.research_tab.research_payload.get("ui_constraint_rows", [])
            if isinstance(ui_rows, list):
                for row in ui_rows:
                    related_path = getattr(row, "related_path", "")
                    if str(related_path or "").replace("\\", "/").strip("/").casefold() != target_key:
                        continue
                    ui_warning = str(getattr(row, "warning_text", "") or "")
                    if ui_warning:
                        break
        except Exception:
            ui_warning = ""
        original_root_text = self.original_dds_edit.text().strip()
        output_root_text = self.output_root_edit.text().strip()
        original_path = Path(original_root_text).expanduser() / relative_path if original_root_text else None
        output_path = Path(output_root_text).expanduser() / relative_path if output_root_text else None

        summaries: List[str] = []
        details: List[str] = []
        for label, path in (("Original", original_path), ("Output", output_path)):
            if path is None or not path.exists():
                continue
            try:
                entry = build_single_texture_processing_plan(
                    normalized,
                    path,
                    relative_path=relative_path,
                )
            except Exception:
                continue
            summary = f"{label}: {entry.action} | {entry.profile.key} | {entry.path_kind}"
            if entry.preserve_reason:
                summary += f" | {entry.preserve_reason}"
            if ui_warning:
                summary += f" | UI note: {ui_warning}"
            summaries.append(summary)
            details.append(summary)

        return " ; ".join(summaries), "\n".join(details)

    def _render_compare_preview(self, relative_path: Path) -> None:
        if self._shutting_down:
            return
        if self._startup_benchmark_enabled():
            return
        texconv_text = self.texconv_path_edit.text().strip()
        original_root_text = self.original_dds_edit.text().strip()
        output_root_text = self.output_root_edit.text().strip()

        texconv_path = Path(texconv_text).expanduser() if texconv_text else None
        original_path = Path(original_root_text).expanduser() / relative_path if original_root_text else None
        output_path = Path(output_root_text).expanduser() / relative_path if output_root_text else None
        original_planner_summary, output_planner_summary = self._summarize_compare_planner(relative_path)
        request_id = self.compare_preview_request_id + 1
        self.compare_preview_request_id = request_id

        self.original_preview_meta_label.setText("")
        self.output_preview_meta_label.setText("")
        self.original_preview_label.clear_preview("Loading preview...")
        self.output_preview_label.clear_preview("Loading preview...")

        if self.compare_preview_thread is not None:
            self.pending_compare_preview_request = (request_id, relative_path)
            if self.compare_preview_worker is not None:
                self.compare_preview_worker.stop()
            return

        self._start_compare_preview_worker(
            request_id,
            texconv_path,
            original_path,
            output_path,
            original_planner_summary,
            output_planner_summary or original_planner_summary,
        )

    def _start_compare_preview_worker(
        self,
        request_id: int,
        texconv_path: Optional[Path],
        original_path: Optional[Path],
        output_path: Optional[Path],
        original_planner_summary: str = "",
        output_planner_summary: str = "",
    ) -> None:
        if self._shutting_down:
            return
        worker = ComparePreviewWorker(
            request_id,
            texconv_path,
            original_path,
            output_path,
            original_planner_summary,
            output_planner_summary,
        )
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_compare_preview_ready)
        worker.error.connect(self._handle_compare_preview_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_compare_preview_refs)

        self.compare_preview_worker = worker
        self.compare_preview_thread = thread
        thread.start()

    def _handle_compare_preview_ready(self, request_id: int, payload: object) -> None:
        if self._shutting_down or request_id != self.compare_preview_request_id:
            return
        if not isinstance(payload, dict):
            return

        original_result = payload.get("original")
        output_result = payload.get("output")
        if isinstance(original_result, ComparePreviewPaneResult):
            self._apply_compare_preview_result(
                self.original_preview_label,
                self.original_preview_meta_label,
                original_result,
            )
        if isinstance(output_result, ComparePreviewPaneResult):
            self._apply_compare_preview_result(
                self.output_preview_label,
                self.output_preview_meta_label,
                output_result,
            )

    def _handle_compare_preview_error(self, request_id: int, message: str) -> None:
        if self._shutting_down or request_id != self.compare_preview_request_id:
            return
        self.original_preview_meta_label.setText("")
        self.output_preview_meta_label.setText("")
        self.original_preview_label.clear_preview(message)
        self.output_preview_label.clear_preview(message)

    def _apply_compare_preview_result(
        self,
        label: PreviewLabel,
        meta_label: QLabel,
        result: ComparePreviewPaneResult,
    ) -> None:
        if result.status != "ok":
            meta_label.setText("")
            label.clear_preview(result.message)
            return

        preview_image_path = str(result.preview_png_path)
        preview_image = result.preview_image
        if preview_image is not None:
            meta_label.setText(result.metadata_summary)
            label.set_preview_image(preview_image, result.title)
            return
        if not preview_image_path:
            meta_label.setText("")
            label.clear_preview("Qt could not load the generated PNG preview.")
            return
        meta_label.setText(result.metadata_summary)
        label.set_preview_image_path(preview_image_path, result.title)

    def _cleanup_compare_preview_refs(self) -> None:
        self.compare_preview_thread = None
        self.compare_preview_worker = None
        if self._shutting_down:
            self.pending_compare_preview_request = None
            return
        if self.pending_compare_preview_request is None:
            return

        request_id, relative_path = self.pending_compare_preview_request
        self.pending_compare_preview_request = None
        texconv_text = self.texconv_path_edit.text().strip()
        original_root_text = self.original_dds_edit.text().strip()
        output_root_text = self.output_root_edit.text().strip()
        texconv_path = Path(texconv_text).expanduser() if texconv_text else None
        original_path = Path(original_root_text).expanduser() / relative_path if original_root_text else None
        output_path = Path(output_root_text).expanduser() / relative_path if output_root_text else None
        original_planner_summary, output_planner_summary = self._summarize_compare_planner(relative_path)
        self._start_compare_preview_worker(
            request_id,
            texconv_path,
            original_path,
            output_path,
            original_planner_summary,
            output_planner_summary or original_planner_summary,
        )
