from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import List, Optional

from PySide6.QtCore import QThread

from cdmw.models import ArchivePreviewResult, ReplaceAssistantItem
from cdmw.ui.replace_assistant.workers import ReplaceAssistantPreviewWorker, ReplaceAssistantUIConstraintWorker


class ReplaceAssistantPreviewMixin:
    def _schedule_preview(self, item: ReplaceAssistantItem) -> None:
        if self.preview_refresh_suspended:
            return
        self.preview_request_id += 1
        request_id = self.preview_request_id
        combined_warning = self._combined_item_warning(item)
        self.preview_title_label.setText(item.source_path.name)
        self.preview_meta_label.setText("Preparing preview...")
        self.preview_warning_label.setVisible(bool(combined_warning))
        self.preview_warning_label.setText(combined_warning)
        self._set_preview_details_text(item)
        if self.preview_worker is not None:
            self.preview_worker.stop()
        if self.preview_thread is not None:
            self.pending_preview_item = item
            return
        self._start_preview_worker(request_id, item)

    def _start_preview_worker(self, request_id: int, item: ReplaceAssistantItem) -> None:
        texconv_text = self.get_texconv_path().strip()
        texconv_path = Path(texconv_text).expanduser() if texconv_text else None
        worker = ReplaceAssistantPreviewWorker(
            request_id,
            texconv_path,
            item.source_path,
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
        self._update_controls()

    def _handle_preview_ready(self, request_id: int, payload: object) -> None:
        if self.preview_refresh_suspended:
            return
        if request_id != self.preview_request_id or not isinstance(payload, ArchivePreviewResult):
            return
        item = self._current_item()
        ui_warning = self._ui_constraint_warning_for_item(item) if item is not None else ""
        combined_warning = "\n".join(part for part in [payload.warning_text, ui_warning] if part).strip()
        self.preview_title_label.setText(payload.title or "Preview")
        self.preview_meta_label.setText(payload.metadata_summary or "")
        self.preview_warning_label.setVisible(bool(combined_warning))
        self.preview_warning_label.setText(combined_warning)
        self._set_preview_details_text(item, payload.detail_text or "")
        if payload.preview_image is not None:
            self.preview_label.set_preview_image(payload.preview_image, payload.metadata_summary or payload.title or "Preview")
        elif payload.preview_image_path:
            self.preview_label.set_preview_image_path(payload.preview_image_path, payload.metadata_summary or payload.title or "Preview")
        else:
            self.preview_label.clear_preview("No preview available.")
        self.preview_zoom_value.setText("Fit" if self.preview_label.current_display_scale() >= 0.999 else f"{self.preview_label.current_display_scale():.0%}")

    def _handle_preview_error(self, request_id: int, message: str) -> None:
        if self.preview_refresh_suspended:
            return
        if request_id != self.preview_request_id:
            return
        self.preview_title_label.setText("Preview failed")
        self.preview_meta_label.setText(message)
        self.preview_warning_label.setVisible(True)
        self.preview_warning_label.setText(message)
        self.preview_label.clear_preview("Preview failed.")
        self.preview_details_edit.setPlainText(message)

    def _ui_constraint_target_path_for_item(self, item: Optional[ReplaceAssistantItem]) -> str:
        if item is None or item.matched_original is None:
            return ""
        return (
            item.matched_original.archive_relative_path
            or item.detected_relative_path
            or ""
        ).strip()

    def _set_preview_details_text(self, item: Optional[ReplaceAssistantItem], base_detail_text: str = "") -> None:
        lines: List[str] = []
        if base_detail_text.strip():
            for raw_line in base_detail_text.strip().splitlines():
                if raw_line.startswith("UI constraint warning:"):
                    continue
                lines.append(raw_line)
        elif item is not None:
            lines.extend(
                [
                    f"Source: {item.source_path}",
                    f"Type: {item.source_kind}",
                    f"Matched original: {item.matched_original.archive_relative_path if item.matched_original else 'Unmatched'}",
                    f"Package: {item.matched_original.package_root if item.matched_original else item.detected_package_root}",
                    f"Status: {item.status}",
                    f"Detail: {item.status_detail}",
                ]
            )
        target_path = self._ui_constraint_target_path_for_item(item)
        ui_warning = self._ui_constraint_warning_for_item(item)
        if target_path:
            cache_key = target_path.casefold()
            display_warning = ui_warning if ui_warning else ("none" if cache_key in self._ui_constraint_warning_cache else "checking...")
            lines.append(f"UI constraint warning: {display_warning}")
        else:
            lines.append("UI constraint warning: none")
        self.preview_details_edit.setPlainText("\n".join(line for line in lines if line))

    def _start_ui_constraint_worker(self, target_path: str) -> None:
        self.ui_constraint_request_id += 1
        request_id = self.ui_constraint_request_id
        self._active_ui_constraint_target = target_path
        worker = ReplaceAssistantUIConstraintWorker(request_id, self.get_archive_entries(), target_path)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_ui_constraint_ready)
        worker.error.connect(self._handle_ui_constraint_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_ui_constraint_refs)
        self.ui_constraint_worker = worker
        self.ui_constraint_thread = thread
        thread.start()

    def _looks_like_ui_constraint_candidate(self, target_path: str) -> bool:
        normalized = str(target_path or "").replace("\\", "/").lower()
        if not normalized:
            return False
        ui_tokens = ("/ui/", "/icon/", "/hud/", "/menu/", "/widget/")
        name_tokens = ("itemicon", "ui_", "icon_", "hud_", "menu_")
        name = PurePosixPath(normalized).name
        return any(token in normalized for token in ui_tokens) or any(token in name for token in name_tokens)

    def _ensure_ui_constraint_warning(self, item: Optional[ReplaceAssistantItem]) -> None:
        target_path = self._ui_constraint_target_path_for_item(item)
        if not target_path:
            self._pending_ui_constraint_target = ""
            return
        cache_key = target_path.casefold()
        if cache_key in self._ui_constraint_warning_cache:
            self._pending_ui_constraint_target = ""
            return
        if not self._looks_like_ui_constraint_candidate(target_path):
            self._ui_constraint_warning_cache[cache_key] = ""
            self._pending_ui_constraint_target = ""
            return
        if self._active_ui_constraint_target.casefold() == cache_key:
            self._pending_ui_constraint_target = ""
            return
        pending_target = self._pending_ui_constraint_target.strip()
        if pending_target and pending_target.casefold() == cache_key:
            return
        if self.ui_constraint_thread is not None:
            self._pending_ui_constraint_target = target_path
            return
        self._pending_ui_constraint_target = ""
        self._start_ui_constraint_worker(target_path)

    def _handle_ui_constraint_ready(self, request_id: int, target_path: str, warning_text: str) -> None:
        if request_id != self.ui_constraint_request_id:
            return
        self._ui_constraint_warning_cache[target_path.casefold()] = warning_text
        current_item = self._current_item()
        if self._ui_constraint_target_path_for_item(current_item).casefold() != target_path.casefold():
            return
        combined_warning = self._combined_item_warning(current_item)
        self.preview_warning_label.setVisible(bool(combined_warning))
        self.preview_warning_label.setText(combined_warning)
        self._set_preview_details_text(current_item, self.preview_details_edit.toPlainText())

    def _handle_ui_constraint_error(self, request_id: int, _message: str) -> None:
        if request_id != self.ui_constraint_request_id:
            return

    def _ui_constraint_warning_for_item(self, item: Optional[ReplaceAssistantItem]) -> str:
        target_path = self._ui_constraint_target_path_for_item(item)
        if not target_path:
            return ""
        return self._ui_constraint_warning_cache.get(target_path.casefold(), "")

    def _combined_item_warning(self, item: Optional[ReplaceAssistantItem]) -> str:
        if item is None:
            return ""
        return "\n".join(part for part in [item.warning, self._ui_constraint_warning_for_item(item)] if part).strip()

    def _cleanup_preview_refs(self) -> None:
        self.preview_thread = None
        self.preview_worker = None
        if self.preview_refresh_suspended:
            self.pending_preview_item = None
        elif hasattr(self, "pending_preview_item") and self.pending_preview_item is not None:
            item = self.pending_preview_item
            self.pending_preview_item = None
            self.preview_request_id += 1
            self._start_preview_worker(self.preview_request_id, item)
        self._update_controls()

    def _adjust_preview_zoom(self, step: int) -> None:
        current = self.preview_label.current_display_scale()
        factor = max(0.1, current * (1.15 if step > 0 else 0.87))
        self._set_preview_zoom_factor(factor)

    def _set_preview_fit(self, fit_to_view: bool) -> None:
        self.preview_label.set_fit_to_view(fit_to_view)
        self.preview_zoom_value.setText("Fit" if fit_to_view else f"{self.preview_label.current_display_scale():.0%}")

    def _set_preview_zoom_factor(self, factor: float) -> None:
        self.preview_label.set_fit_to_view(False)
        self.preview_label.set_zoom_factor(factor)
        self.preview_zoom_value.setText(f"{factor:.0%}")
