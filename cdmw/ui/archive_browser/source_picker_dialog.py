"""Archive mesh/source picker dialog."""
from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtGui import QBrush, QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.constants import DEFAULT_UI_THEME
from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS
from cdmw.services.texture_workflow_service import SourceMixCandidate, source_mix_role_for_virtual_path
from cdmw.models import ArchiveEntry, ArchivePreviewResult, ModelPreviewData
from cdmw.ui.themes import get_theme
from cdmw.workers.archive_preview_workers import ArchivePreviewWorker


class ArchiveSourcePickerDialogMixin:
    def _choose_archive_mesh_source_dialog(
        self,
        parent: QWidget,
        *,
        title: str,
        entries: Sequence[ArchiveEntry] = (),
        candidates: Sequence[SourceMixCandidate] = (),
        prompt: str = "Search archive source",
        allowed_extensions: Sequence[str] = (),
        excluded_entry: Optional[ArchiveEntry] = None,
    ) -> Optional[object]:
        source_entries = entries or ()
        source_candidates = candidates or ()
        if not source_entries and not source_candidates:
            return None
        allowed_extension_set = {
            str(extension or "").strip().lower()
            for extension in allowed_extensions
            if str(extension or "").strip()
        }
        excluded_key = (
            (
                str(excluded_entry.path or "").replace("\\", "/").strip().casefold(),
                str(excluded_entry.pamt_path).strip().casefold(),
                int(excluded_entry.offset),
            )
            if isinstance(excluded_entry, ArchiveEntry)
            else None
        )

        dialog = QDialog(parent)
        dialog.setWindowTitle(title)
        dialog.resize(1180, 700)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        control_row = QHBoxLayout()
        control_row.setContentsMargins(0, 0, 0, 0)
        control_row.setSpacing(8)
        search_edit = QLineEdit()
        search_edit.setPlaceholderText(prompt)
        extension_combo = QComboBox()
        extension_combo.setMinimumWidth(150)
        extension_combo.addItem("All supported", "")
        for extension in sorted(allowed_extension_set):
            extension_combo.addItem(extension, extension)
        extension_combo.setToolTip("Filter source candidates to one archive extension.")
        control_row.addWidget(search_edit, 1)
        control_row.addWidget(QLabel("Extension"))
        control_row.addWidget(extension_combo)
        layout.addLayout(control_row)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        tree = QTreeWidget()
        tree.setColumnCount(6)
        tree.setHeaderLabels(["Name", "Ext", "Role", "Path", "Package / Source", "Size"])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.setSelectionMode(QAbstractItemView.SingleSelection)
        tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tree.header().setStretchLastSection(False)
        tree.header().resizeSection(0, 220)
        tree.header().resizeSection(1, 70)
        tree.header().resizeSection(2, 140)
        tree.header().resizeSection(3, 390)
        tree.header().resizeSection(4, 160)
        tree.header().resizeSection(5, 90)
        splitter.addWidget(tree)

        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(8, 0, 0, 0)
        preview_layout.setSpacing(6)
        preview_title = QLabel("Source Preview")
        preview_title.setObjectName("HintLabel")
        preview_layout.addWidget(preview_title)
        preview_widget = QLabel("Select a .pac/.pam/.pamlod source to preview it.")
        preview_widget.setAlignment(Qt.AlignCenter)
        preview_widget.setWordWrap(True)
        preview_widget.setFrameShape(QFrame.Shape.StyledPanel)
        preview_widget.setMinimumWidth(340)
        preview_widget.setMinimumHeight(280)
        preview_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        preview_layout.addWidget(preview_widget, 1)
        preview_status = QLabel(
            "Static geometry thumbnail only; textures and live texture uploads are skipped here so source browsing stays responsive."
        )
        preview_status.setObjectName("HintLabel")
        preview_status.setWordWrap(True)
        preview_layout.addWidget(preview_status)
        splitter.addWidget(preview_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([720, 420])
        layout.addWidget(splitter, 1)

        progress = QProgressBar()
        progress.setTextVisible(True)
        progress.setVisible(False)
        layout.addWidget(progress)
        status = QLabel("Type to filter the indexed source list. This does not rescan the archive.")
        status.setObjectName("HintLabel")
        status.setWordWrap(True)
        layout.addWidget(status)
        result: Dict[str, object] = {}
        population_timer = QTimer(dialog)
        population_timer.setSingleShot(True)
        refresh_timer = QTimer(dialog)
        refresh_timer.setSingleShot(True)
        refresh_timer.setInterval(120)
        population_generation = {"value": 0}
        population_state: Dict[str, object] = {}
        max_visible_rows = 1500

        def _entry_key_local(source_entry: ArchiveEntry) -> Tuple[str, str, int]:
            return (
                str(source_entry.path or "").replace("\\", "/").strip().casefold(),
                str(source_entry.pamt_path).strip().casefold(),
                int(source_entry.offset),
            )

        def _selected_extension() -> str:
            return str(extension_combo.currentData() or "").strip().lower()

        def _entry_extension(source_entry: ArchiveEntry) -> str:
            return str(source_entry.extension or "").strip().lower()

        def _candidate_extension(candidate: SourceMixCandidate) -> str:
            return str(candidate.extension or "").strip().lower()

        def _extension_allowed(extension: str) -> bool:
            normalized = str(extension or "").strip().lower()
            selected_extension = _selected_extension()
            if allowed_extension_set and normalized not in allowed_extension_set:
                return False
            if selected_extension and normalized != selected_extension:
                return False
            return True

        def _row_for_entry(source_entry: ArchiveEntry) -> Optional[Dict[str, object]]:
            extension = _entry_extension(source_entry)
            if not _extension_allowed(extension):
                return None
            if excluded_key is not None and _entry_key_local(source_entry) == excluded_key:
                return None
            return {
                "name": source_entry.basename,
                "extension": extension,
                "path": source_entry.path.replace("\\", "/"),
                "package": source_entry.package_label,
                "role": self._archive_entry_role_label(source_entry),
                "size": int(source_entry.orig_size or source_entry.comp_size or 0),
                "value": source_entry,
            }

        def _row_for_candidate(candidate: SourceMixCandidate) -> Optional[Dict[str, object]]:
            extension = _candidate_extension(candidate)
            if not _extension_allowed(extension):
                return None
            source_entry = candidate.source_archive_entry
            if isinstance(source_entry, ArchiveEntry) and excluded_key is not None and _entry_key_local(source_entry) == excluded_key:
                return None
            display_path = candidate.display_path.replace("\\", "/")
            return {
                "name": PurePosixPath(display_path).name,
                "extension": extension,
                "path": display_path,
                "package": candidate.layer.label,
                "role": candidate.role or source_mix_role_for_virtual_path(display_path),
                "size": int(candidate.size or 0),
                "value": candidate,
            }

        def _matches(row: Mapping[str, object], terms: Sequence[str]) -> bool:
            if not terms:
                return True
            haystack = " ".join(
                str(row.get(key, "") or "")
                for key in ("name", "extension", "role", "path", "package")
            ).casefold()
            return all(term in haystack for term in terms)

        def _add_source_row(row: Mapping[str, object]) -> None:
            item = QTreeWidgetItem(
                [
                    str(row.get("name", "") or "-"),
                    str(row.get("extension", "") or "-"),
                    str(row.get("role", "") or "-"),
                    str(row.get("path", "") or "-"),
                    str(row.get("package", "") or "-"),
                    f"{int(row.get('size', 0) or 0):,}",
                ]
            )
            item.setData(0, Qt.UserRole, row.get("value"))
            for column in range(tree.columnCount()):
                item.setToolTip(column, item.text(column))
            if str(row.get("extension", "") or "").lower() in ARCHIVE_MESH_EXTENSIONS:
                item.setForeground(1, QBrush(QColor("#86efac")))
            tree.addTopLevelItem(item)

        def _set_source_preview_message(message: str) -> None:
            preview_widget.clear()
            preview_widget.setText(str(message or ""))

        def _source_preview_value(value: object) -> Optional[ArchiveEntry]:
            if isinstance(value, ArchiveEntry) and value.extension in ARCHIVE_MESH_EXTENSIONS:
                return value
            if isinstance(value, SourceMixCandidate):
                source_entry = value.source_archive_entry
                if isinstance(source_entry, ArchiveEntry) and source_entry.extension in ARCHIVE_MESH_EXTENSIONS:
                    return source_entry
            return None

        preview_state: Dict[str, object] = {"request_id": 0, "worker": None, "thread": None, "closed": False}
        preview_cache: Dict[Tuple[str, str, int], ArchivePreviewResult] = {}

        def _stop_source_preview_worker() -> None:
            preview_state["request_id"] = int(preview_state.get("request_id", 0) or 0) + 1
            worker = preview_state.get("worker")
            thread = preview_state.get("thread")
            if isinstance(worker, ArchivePreviewWorker):
                worker.stop()
            if isinstance(thread, QThread):
                thread.quit()
            preview_state["worker"] = None
            preview_state["thread"] = None

        def _show_source_preview_result(source_entry: ArchiveEntry, payload: ArchivePreviewResult) -> None:
            preview_model = getattr(payload, "preview_model", None)
            if not isinstance(preview_model, ModelPreviewData):
                _set_source_preview_message(f"No renderable model preview was recovered for {source_entry.basename}.")
                preview_status.setText(f"{source_entry.basename}: no renderable model preview recovered.")
                return
            image = getattr(payload, "static_preview_image", None)
            if not isinstance(image, QImage) or image.isNull():
                _set_source_preview_message(f"No renderable geometry was recovered for {source_entry.basename}.")
                preview_status.setText(f"{source_entry.basename}: no renderable geometry recovered.")
                return
            preview_widget.clear()
            preview_widget.setPixmap(QPixmap.fromImage(image))
            preview_status.setText(
                f"Previewing {source_entry.path} | "
                f"{int(getattr(preview_model, 'vertex_count', 0) or 0):,} vertices, "
                f"{int(getattr(preview_model, 'face_count', 0) or 0):,} faces"
            )

        def _handle_source_preview_ready(request_id: int, payload: object) -> None:
            if bool(preview_state.get("closed")) or request_id != int(preview_state.get("request_id", 0) or 0):
                return
            source_entry = preview_state.get("entry")
            if not isinstance(source_entry, ArchiveEntry) or not isinstance(payload, ArchivePreviewResult):
                return
            preview_cache[_entry_key_local(source_entry)] = payload
            _show_source_preview_result(source_entry, payload)

        def _handle_source_preview_error(request_id: int, message: str) -> None:
            if bool(preview_state.get("closed")) or request_id != int(preview_state.get("request_id", 0) or 0):
                return
            source_entry = preview_state.get("entry")
            label = source_entry.basename if isinstance(source_entry, ArchiveEntry) else "selected source"
            _set_source_preview_message(f"Could not build preview for {label}.")
            preview_status.setText(f"Preview failed for {label}: {message}")

        def _clear_source_preview_worker(request_id: int) -> None:
            if request_id == int(preview_state.get("request_id", 0) or 0):
                preview_state["worker"] = None
                preview_state["thread"] = None

        def _update_source_preview(value: object) -> None:
            source_entry = _source_preview_value(value)
            if not isinstance(source_entry, ArchiveEntry):
                _stop_source_preview_worker()
                _set_source_preview_message("Select a .pac/.pam/.pamlod archive source to preview it.")
                preview_status.setText("Preview is available for archive-backed mesh sources.")
                return
            cache_key = _entry_key_local(source_entry)
            cached = preview_cache.get(cache_key)
            if cached is not None:
                _stop_source_preview_worker()
                preview_state["entry"] = source_entry
                _show_source_preview_result(source_entry, cached)
                return
            _stop_source_preview_worker()
            request_id = int(preview_state.get("request_id", 0) or 0) + 1
            preview_state["request_id"] = request_id
            preview_state["entry"] = source_entry
            _set_source_preview_message(f"Loading preview for {source_entry.basename}...")
            preview_status.setText(f"Building geometry preview for {source_entry.path}...")
            preview_settings = self._current_model_preview_render_settings()
            preview_theme = get_theme(str(getattr(self, "current_theme_key", DEFAULT_UI_THEME) or DEFAULT_UI_THEME))
            worker = ArchivePreviewWorker(
                request_id,
                source_entry,
                self._find_archive_preview_companion_entry(source_entry),
                self.archive_entries_by_normalized_path,
                self.archive_entries_by_basename,
                self.archive_sidecar_entries_by_texture_path,
                self.archive_sidecar_entries_by_texture_basename,
                self._collect_archive_preview_loose_roots(),
                visible_texture_mode=preview_settings.visible_texture_mode,
                support_texture_slots=(),
                render_settings=preview_settings,
                include_loose_preview_assets=False,
                sidecar_generation=self.archive_sidecar_generation,
                attach_preview_images=False,
                static_thumbnail_size=(preview_widget.width(), preview_widget.height()),
                static_thumbnail_text_color=str(preview_theme.get("text_muted", "#8b949e")),
                static_thumbnail_point_cloud=True,
            )
            thread = QThread(self)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.completed.connect(_handle_source_preview_ready)
            worker.error.connect(_handle_source_preview_error)
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(lambda rid=request_id: _clear_source_preview_worker(rid))
            preview_state["worker"] = worker
            preview_state["thread"] = thread
            thread.start()

        def _refresh_select_button() -> None:
            item = tree.currentItem()
            select_button.setEnabled(item is not None and item.data(0, Qt.UserRole) is not None)

        def _continue_source_picker_population() -> None:
            if not population_state:
                return
            generation = int(population_state.get("generation", 0) or 0)
            if generation != int(population_generation.get("value", 0) or 0):
                population_state.clear()
                return
            terms = tuple(population_state.get("terms") or ())
            total = int(population_state.get("total", 0) or 0)
            deadline = time.perf_counter() + 0.018
            tree.setUpdatesEnabled(False)
            try:
                while time.perf_counter() < deadline:
                    if int(population_state.get("shown", 0) or 0) >= max_visible_rows:
                        population_state["done"] = True
                        break
                    phase = str(population_state.get("phase") or "entries")
                    if phase == "entries":
                        index = int(population_state.get("entry_index", 0) or 0)
                        if index >= len(source_entries):
                            population_state["phase"] = "candidates"
                            continue
                        source_entry = source_entries[index]
                        population_state["entry_index"] = index + 1
                        population_state["processed"] = int(population_state.get("processed", 0) or 0) + 1
                        if not isinstance(source_entry, ArchiveEntry):
                            continue
                        row = _row_for_entry(source_entry)
                    elif phase == "candidates":
                        index = int(population_state.get("candidate_index", 0) or 0)
                        if index >= len(source_candidates):
                            population_state["done"] = True
                            break
                        candidate = source_candidates[index]
                        population_state["candidate_index"] = index + 1
                        population_state["processed"] = int(population_state.get("processed", 0) or 0) + 1
                        if not isinstance(candidate, SourceMixCandidate):
                            continue
                        row = _row_for_candidate(candidate)
                    else:
                        population_state["done"] = True
                        break
                    if row is None or not _matches(row, terms):
                        continue
                    _add_source_row(row)
                    population_state["shown"] = int(population_state.get("shown", 0) or 0) + 1
                    population_state["matched"] = int(population_state.get("matched", 0) or 0) + 1
            finally:
                tree.setUpdatesEnabled(True)
            processed = min(total, int(population_state.get("processed", 0) or 0))
            progress.setRange(0, max(1, total))
            progress.setValue(processed)
            shown = int(population_state.get("shown", 0) or 0)
            status.setText(
                f"{shown:,} shown while filtering {processed:,} / {total:,} indexed source row(s). "
                "This does not rescan the archive."
            )
            if bool(population_state.get("done")):
                progress.setVisible(False)
                if tree.topLevelItemCount() > 0 and tree.currentItem() is None:
                    tree.setCurrentItem(tree.topLevelItem(0))
                elif tree.topLevelItemCount() <= 0:
                    _update_source_preview(None)
                clipped = " Results are capped; narrow the search or extension filter for more exact matches." if shown >= max_visible_rows else ""
                status.setText(
                    f"{shown:,} shown from cached source rows.{clipped} "
                    "Search by basename, role, path, package, or extension."
                )
                _refresh_select_button()
                population_state.clear()
                return
            population_timer.start(0)

        def _restart_source_picker_population() -> None:
            terms = [part.casefold() for part in search_edit.text().strip().split() if part.strip()]
            population_generation["value"] = int(population_generation.get("value", 0) or 0) + 1
            population_timer.stop()
            population_state.clear()
            tree.clear()
            select_button.setEnabled(False)
            _update_source_preview(None)
            total = len(source_entries) + len(source_candidates)
            progress.setVisible(True)
            progress.setRange(0, max(1, total))
            progress.setValue(0)
            population_state.update(
                {
                    "generation": population_generation["value"],
                    "terms": tuple(terms),
                    "phase": "entries",
                    "entry_index": 0,
                    "candidate_index": 0,
                    "processed": 0,
                    "matched": 0,
                    "shown": 0,
                    "total": total,
                }
            )
            status.setText("Filtering cached source rows...")
            population_timer.start(0)

        def _accept_current() -> None:
            item = tree.currentItem()
            if item is None:
                return
            value = item.data(0, Qt.UserRole)
            if value is None:
                return
            result["value"] = value
            dialog.accept()

        def _handle_source_selection_changed(current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
            _refresh_select_button()
            value = current.data(0, Qt.UserRole) if current is not None else None
            _update_source_preview(value)

        search_edit.textChanged.connect(lambda _text: refresh_timer.start())
        extension_combo.currentIndexChanged.connect(lambda _index: refresh_timer.start())
        refresh_timer.timeout.connect(_restart_source_picker_population)
        population_timer.timeout.connect(_continue_source_picker_population)
        tree.currentItemChanged.connect(_handle_source_selection_changed)
        tree.itemDoubleClicked.connect(lambda _item, _column: _accept_current())
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        select_button = QPushButton("Select")
        select_button.setEnabled(False)
        button_row.addWidget(cancel_button)
        button_row.addWidget(select_button)
        layout.addLayout(button_row)
        cancel_button.clicked.connect(dialog.reject)
        select_button.clicked.connect(_accept_current)
        QTimer.singleShot(0, _restart_source_picker_population)
        search_edit.setFocus(Qt.FocusReason.OtherFocusReason)
        try:
            if dialog.exec() == QDialog.Accepted:
                return result.get("value")
        finally:
            preview_state["closed"] = True
            _stop_source_preview_worker()
        return None
