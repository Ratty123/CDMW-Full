"""Material sidecar value editor dialog."""

from __future__ import annotations

import json, shutil, threading
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Tuple

from PySide6.QtCore import QProcess, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.services.archive_workflow_service import set_model_texture_display_preview_max_dimension
from cdmw.services.material_sidecar_service import (
    export_material_sidecar_mod_package,
)
from cdmw.models import (
    ArchiveEntry,
    ArchivePreviewResult,
    ModelPreviewData,
    ModelPreviewRenderSettings,
    clamp_model_preview_render_settings,
)
from cdmw.services.material_sidecar_document_service import (
    MaterialSidecarEditorDocument,
    MaterialSidecarExportPreparation,
    prepare_material_sidecar_export,
)
from cdmw.services.material_sidecar_preview_service import (
    MaterialSidecarPreviewBuildRequest,
    MaterialSidecarPreviewBuildResult,
    build_material_sidecar_preview,
)
from cdmw.ui.archive_browser import material_sidecar_editor_helpers as material_sidecar_text
from cdmw.ui.archive_browser.material_sidecar_document_controller import (
    ArchiveMaterialSidecarDocumentControllerMixin,
)
from cdmw.ui.archive_browser.material_sidecar_editor_helpers import (
    material_editor_color_from_value,
    material_preview_entry_key,
    material_value_swatch_icon,
    selected_value_ready_for_live_refresh,
)
from cdmw.ui.native_d3d11_preview_host import NativeD3D11PreviewHostFrame
from cdmw.ui.shell.diagnostics_controller import d3d11_status_file_signature as _d3d11_status_file_signature
from cdmw.ui.widgets import make_tree_columns_persistent

class ArchiveMaterialSidecarEditorMixin(ArchiveMaterialSidecarDocumentControllerMixin):
    def _show_material_sidecar_editor(self, document: MaterialSidecarEditorDocument) -> None:
        entry = document.entry
        original_text = document.original_text
        rows = document.rows
        if not rows:
            title, message = material_sidecar_text.material_sidecar_empty_values_dialog_text()
            QMessageBox.information(self, title, message)
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(material_sidecar_text.material_sidecar_editor_window_title(entry.basename))
        dialog.setModal(True)
        dialog.resize(*material_sidecar_text.material_sidecar_dialog_size())
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        intro = QLabel(material_sidecar_text.material_sidecar_editor_intro_text())
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        preview_accuracy_warning = QLabel(material_sidecar_text.material_sidecar_preview_warning_text())
        preview_accuracy_warning.setObjectName("WarningText")
        preview_accuracy_warning.setWordWrap(True)
        layout.addWidget(preview_accuracy_warning)
        content_splitter = QSplitter(Qt.Horizontal)
        editor_panel = QWidget()
        editor_layout = QVBoxLayout(editor_panel)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(8)
        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(8, 0, 0, 0)
        preview_layout.setSpacing(8)
        tree = QTreeWidget()
        tree.setColumnCount(5)
        tree.setHeaderLabels(list(material_sidecar_text.material_sidecar_tree_headers()))
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        tree.setSelectionMode(QAbstractItemView.SingleSelection)
        material_value_swatch_icons: Dict[str, QIcon] = {}
        def _update_material_value_swatch(item: Optional[QTreeWidgetItem]) -> None:
            if item is None:
                return
            blocker = QSignalBlocker(tree)
            try:
                if item.text(1).strip().lower() != "color":
                    item.setIcon(3, QIcon())
                    return
                color = material_editor_color_from_value(item.text(3))
                if color is None:
                    item.setIcon(3, QIcon())
                    item.setToolTip(3, item.text(3))
                    return
                item.setIcon(3, material_value_swatch_icon(color, material_value_swatch_icons))
                item.setToolTip(3, material_sidecar_text.material_sidecar_preview_color_tooltip(item.text(3), color.name()))
            finally:
                del blocker
        for row in rows:
            item = material_sidecar_text.material_sidecar_value_tree_item(row)
            _update_material_value_swatch(item)
            tree.addTopLevelItem(item)
        header = tree.header()
        header.setStretchLastSection(False)
        for section, width in enumerate(material_sidecar_text.material_sidecar_tree_column_widths()):
            header.resizeSection(section, width)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        make_tree_columns_persistent(
            tree,
            self.settings,
            "dialog/material_sidecar_values",
            minimum_width=56,
            save_callback=self.schedule_settings_save,
        )
        editor_layout.addWidget(tree, stretch=1)

        selected_value_row = QGridLayout()
        selected_value_row.setHorizontalSpacing(8)
        selected_value_label = QLabel(material_sidecar_text.material_sidecar_selected_value_label_text())
        selected_value_edit = QLineEdit()
        selected_value_edit.setPlaceholderText(material_sidecar_text.material_sidecar_selected_value_placeholder_text())
        selected_value_edit.setClearButtonEnabled(True)
        selected_value_edit.setToolTip(material_sidecar_text.material_sidecar_value_edit_tooltip_text())
        selected_value_swatch = QFrame()
        selected_value_swatch.setObjectName("SelectedMaterialValueColorSwatch")
        selected_value_swatch.setFixedSize(28, 28)
        selected_value_swatch.setToolTip(material_sidecar_text.material_sidecar_selected_color_tooltip_text())
        selected_value_row.addWidget(selected_value_label, 0, 0)
        selected_value_row.addWidget(selected_value_edit, 0, 1)
        selected_value_row.addWidget(selected_value_swatch, 0, 2)
        selected_value_row.setColumnStretch(1, 1)
        editor_layout.addLayout(selected_value_row)
        selected_detail_label = QLabel("")
        selected_detail_label.setObjectName("HintLabel")
        selected_detail_label.setWordWrap(True)
        editor_layout.addWidget(selected_detail_label)

        preview_header_row = QHBoxLayout()
        show_preview_label, refresh_preview_label, preview_settings_label, live_preview_label = (
            material_sidecar_text.material_sidecar_preview_control_labels()
        )
        show_preview_button = QPushButton(show_preview_label)
        refresh_preview_button = QPushButton(refresh_preview_label)
        material_preview_settings_button = QPushButton(preview_settings_label)
        material_preview_settings_button.setToolTip(material_sidecar_text.material_sidecar_preview_settings_tooltip_text())
        live_preview_checkbox = QCheckBox(live_preview_label)
        live_preview_checkbox.setChecked(True)
        preview_header_row.addWidget(show_preview_button)
        preview_header_row.addWidget(refresh_preview_button)
        preview_header_row.addWidget(material_preview_settings_button)
        preview_header_row.addWidget(live_preview_checkbox)
        preview_header_row.addStretch(1)
        preview_layout.addLayout(preview_header_row)
        preview_status_label = QLabel(material_sidecar_text.material_sidecar_initial_preview_status_text())
        preview_status_label.setObjectName("HintLabel")
        preview_status_label.setWordWrap(True)
        preview_layout.addWidget(preview_status_label)
        material_preview_host = NativeD3D11PreviewHostFrame(dialog)
        material_preview_host.setObjectName("MaterialValuesNativeD3D11PreviewHost")
        material_preview_host.setAttribute(Qt.WA_NativeWindow, True)
        material_preview_host.setMinimumSize(*material_sidecar_text.material_sidecar_preview_host_minimum_size())
        material_preview_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        material_preview_process_state: Dict[str, object] = material_sidecar_text.material_sidecar_preview_process_state()
        material_preview_packages: List[Path] = []

        def _material_value_preview_render_settings(*, material_effects_active: bool = False) -> ModelPreviewRenderSettings:
            del material_effects_active
            return clamp_model_preview_render_settings(self._current_model_preview_render_settings())

        def _configure_material_value_preview_host(*, material_effects_active: bool = False) -> None:
            preview_settings = _material_value_preview_render_settings(material_effects_active=material_effects_active)
            set_model_texture_display_preview_max_dimension(
                preview_settings.preview_texture_max_dimension,
                low_quality_value=preview_settings.low_quality_texture_max_dimension,
            )
            material_preview_host.set_render_tuning(preview_settings)

        _configure_material_value_preview_host()
        preview_layout.addWidget(material_preview_host, stretch=1)
        content_splitter.addWidget(editor_panel)
        content_splitter.addWidget(preview_panel)
        content_splitter.setStretchFactor(0, 3)
        content_splitter.setStretchFactor(1, 2)
        content_splitter.setSizes(list(material_sidecar_text.material_sidecar_content_splitter_sizes()))
        layout.addWidget(content_splitter, stretch=1)

        button_row = QHBoxLayout()
        pick_color_label, reset_label, export_label, close_label = material_sidecar_text.material_sidecar_action_button_labels()
        pick_color_button = QPushButton(pick_color_label)
        reset_button = QPushButton(reset_label)
        export_button = QPushButton(export_label)
        close_button = QPushButton(close_label)
        button_row.addWidget(pick_color_button)
        button_row.addWidget(reset_button)
        button_row.addStretch(1)
        button_row.addWidget(export_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        def _current_item() -> Optional[QTreeWidgetItem]:
            item = tree.currentItem()
            return item if item is not None and item.data(0, Qt.UserRole) else None

        syncing_selected_value = material_sidecar_text.material_sidecar_selected_value_sync_state()
        selected_value_pending_edits: Dict[str, str] = {}

        def _update_selected_value_swatch(item: Optional[QTreeWidgetItem]) -> None:
            if item is None or item.text(1).strip().lower() != "color":
                selected_value_swatch.setVisible(False)
                return
            color = material_editor_color_from_value(selected_value_edit.text() or item.text(3))
            if color is None:
                selected_value_swatch.setVisible(False)
                return
            selected_value_swatch.setVisible(True)
            selected_value_swatch.setStyleSheet(
                material_sidecar_text.material_sidecar_selected_color_swatch_stylesheet(color.name(QColor.HexRgb))
            )
            selected_value_swatch.setToolTip(material_sidecar_text.material_sidecar_selected_color_tooltip_text(color.name()))

        def _sync_selected_value_from_tree() -> None:
            item = _current_item()
            syncing_selected_value["active"] = True
            try:
                selected_value_edit.setEnabled(item is not None)
                selected_value_edit.setText(item.text(3) if item is not None else "")
                selected_value_edit.setToolTip(item.text(3) if item is not None else "")
                _update_selected_value_swatch(item)
                if item is not None:
                    selected_detail_label.setText(
                        material_sidecar_text.material_sidecar_selected_detail_text(item.text(0), item.text(2), item.text(4))
                    )
                else:
                    selected_detail_label.clear()
            finally:
                syncing_selected_value["active"] = False

        def _record_selected_value_pending_edit(item: Optional[QTreeWidgetItem]) -> None:
            if item is None:
                return
            row_id = str(item.data(0, Qt.UserRole) or "")
            if not row_id:
                return
            current_value = item.text(3).strip()
            original_value = str(item.data(3, Qt.UserRole) or "")
            if current_value != original_value:
                selected_value_pending_edits[row_id] = current_value
            else:
                selected_value_pending_edits.pop(row_id, None)

        def _sync_tree_from_selected_value(text: str) -> None:
            if syncing_selected_value["active"]:
                return
            item = _current_item()
            if item is None:
                return
            item.setText(3, str(text or ""))
            item.setToolTip(3, str(text or ""))
            _update_material_value_swatch(item)
            _update_selected_value_swatch(item)
            _record_selected_value_pending_edit(item)
            _schedule_live_preview_for_item(item)
            if material_sidecar_text.material_sidecar_kind_supports_live_preview(item.text(1)) and live_preview_checkbox.isChecked():
                preview_status_label.setText(material_sidecar_text.material_sidecar_live_preview_scheduled_status())
                QTimer.singleShot(
                    material_sidecar_text.material_sidecar_selected_value_live_refresh_interval_ms(),
                    lambda: _start_material_preview_refresh(include_texture_edits=False, live=True)
                    if dialog.isVisible()
                    else None,
                )

        def _handle_material_tree_item_changed(item: QTreeWidgetItem, column: int) -> None:
            if column == 3 and item is _current_item():
                _update_material_value_swatch(item)
                _record_selected_value_pending_edit(item)
                _sync_selected_value_from_tree()
                _schedule_live_preview_for_item(item)

        selected_value_sync_timer = QTimer(dialog)
        selected_value_sync_timer.setInterval(material_sidecar_text.material_sidecar_selected_value_sync_interval_ms())

        def _poll_selected_value_edit() -> None:
            if syncing_selected_value["active"]:
                return
            item = _current_item()
            if item is None:
                return
            if selected_value_edit.text() != item.text(3):
                _sync_tree_from_selected_value(selected_value_edit.text())

        selected_value_sync_timer.timeout.connect(_poll_selected_value_edit)
        selected_value_sync_timer.start()

        def _pick_color() -> None:
            item = _current_item()
            if item is None or item.text(1) != "color":
                return
            color = QColorDialog.getColor(
                self._qcolor_from_material_value(item.text(3)),
                dialog,
                material_sidecar_text.material_sidecar_choose_color_dialog_title(),
            )
            if color.isValid():
                item.setText(3, color.name())
                _update_material_value_swatch(item)
                _record_selected_value_pending_edit(item)
                _sync_selected_value_from_tree()
                _schedule_live_preview_for_item(item)

        def _reset_selected() -> None:
            item = _current_item()
            if item is not None:
                original_value = str(item.data(3, Qt.UserRole) or "")
                item.setText(3, original_value)
                _update_material_value_swatch(item)
                _record_selected_value_pending_edit(item)
                _sync_selected_value_from_tree()
                _schedule_live_preview_for_item(item)

        row_kind_by_id = material_sidecar_text.material_sidecar_row_kind_by_id(rows)
        preview_model_entry_state = material_sidecar_text.material_sidecar_preview_model_entry_state()
        preview_status_label.setText(material_sidecar_text.material_sidecar_lookup_pending_status())
        show_preview_button.setEnabled(False)
        refresh_preview_button.setEnabled(False)

        def _resolve_material_preview_model_entry() -> None:
            preview_model_entry = self._material_sidecar_preview_model_candidate(entry, "")
            preview_model_entry_state["entry"] = preview_model_entry
            preview_model_entry_state["resolved"] = True
            if preview_model_entry is None:
                preview_status_label.setText(material_sidecar_text.material_sidecar_no_preview_model_status())
                show_preview_button.setEnabled(False)
                refresh_preview_button.setEnabled(False)
                return
            preview_status_label.setText(material_sidecar_text.material_sidecar_preview_model_status(preview_model_entry.path))
            show_preview_button.setEnabled(True)
            refresh_preview_button.setEnabled(True)

        def _edited_values(kinds: Optional[set[str]] = None) -> Dict[str, str]:
            edited: Dict[str, str] = {}
            for row_id, current_value in selected_value_pending_edits.items():
                if kinds is not None and row_kind_by_id.get(row_id) not in kinds:
                    continue
                edited[row_id] = current_value
            for index in range(tree.topLevelItemCount()):
                item = tree.topLevelItem(index)
                row_id = str(item.data(0, Qt.UserRole) or "")
                if kinds is not None and row_kind_by_id.get(row_id) not in kinds:
                    continue
                original_value = str(item.data(3, Qt.UserRole) or "")
                current_value = item.text(3).strip()
                if row_id and current_value != original_value:
                    edited[row_id] = current_value
            return edited

        def _sidecar_text_for_preview(*, include_texture_edits: bool) -> str:
            kinds = None if include_texture_edits else material_sidecar_text.material_sidecar_live_preview_kinds()
            edited_values = _edited_values(kinds)
            if not edited_values:
                return original_text
            return apply_material_sidecar_edits(original_text, edited_values).text

        live_preview_timer = QTimer(dialog)
        live_preview_timer.setSingleShot(True)
        live_preview_timer.setInterval(material_sidecar_text.material_sidecar_live_preview_interval_ms())
        selected_value_live_refresh_timer = QTimer(dialog)
        selected_value_live_refresh_timer.setSingleShot(True)
        selected_value_live_refresh_timer.setInterval(
            material_sidecar_text.material_sidecar_selected_value_live_refresh_interval_ms()
        )
        preview_generation = material_sidecar_text.material_sidecar_preview_generation_state()
        material_preview_base_result_state: Dict[str, object] = material_sidecar_text.material_sidecar_preview_base_result_state()
        material_preview_status_timer = QTimer(dialog)
        material_preview_status_timer.setInterval(material_sidecar_text.material_sidecar_preview_status_poll_interval_ms())

        def _material_preview_process_running() -> bool:
            process = material_preview_process_state.get("process")
            return isinstance(process, QProcess) and self._archive_qprocess_state(process) != QProcess.NotRunning

        def _remove_material_preview_package(package_dir: object) -> None:
            if package_dir is None:
                return
            try:
                path = Path(package_dir)
            except (TypeError, ValueError):
                return
            try:
                shutil.rmtree(path, ignore_errors=True)
            except OSError:
                pass

        def _clear_material_preview_packages() -> None:
            for package_dir in list(material_preview_packages):
                _remove_material_preview_package(package_dir)
            material_preview_packages.clear()

        def _stop_material_preview_process() -> None:
            process = material_preview_process_state.get("process")
            material_preview_process_state["process"] = None
            if not isinstance(process, QProcess):
                return

            def _kill_later(target: QProcess = process) -> None:
                try:
                    if target.state() != QProcess.NotRunning:
                        target.kill()
                except RuntimeError:
                    pass

            try:
                if process.state() != QProcess.NotRunning:
                    process.terminate()
                    QTimer.singleShot(material_sidecar_text.material_sidecar_preview_process_kill_delay_ms(), _kill_later)
            except RuntimeError:
                pass

        def _shutdown_material_preview() -> None:
            live_preview_timer.stop()
            material_preview_status_timer.stop()
            preview_generation["value"] += 1
            worker = preview_generation.pop("worker", None)
            if worker is getattr(self, "utility_worker", None):
                worker.stop()
            _stop_material_preview_process()
            QTimer.singleShot(
                material_sidecar_text.material_sidecar_preview_package_cleanup_delay_ms(),
                _clear_material_preview_packages,
            )

        def _apply_material_preview_status_payload(payload: Mapping[str, object]) -> None:
            event = str(payload.get("event", "") or "").strip().lower()
            summary = str(material_preview_process_state.get("summary", "") or "").strip()
            if event == "loaded":
                loaded_message = material_sidecar_text.material_sidecar_native_loaded_status(
                    batch_count=payload.get("batch_count", 0),
                    vertex_count=payload.get("vertex_count", 0),
                    first_frame_ms=payload.get("first_frame_ms", 0.0),
                    texture_failure_count=payload.get("texture_failures", 0),
                )
                preview_status_label.setText(
                    material_sidecar_text.material_sidecar_preview_payload_status(summary, loaded_message)
                )
            elif event == "error":
                preview_status_label.setText(
                    material_sidecar_text.material_sidecar_native_error_status(payload.get("message", ""))
                )

        def _poll_material_preview_status() -> None:
            status_file = material_preview_process_state.get("status_file")
            if status_file is None:
                return
            try:
                status_path = Path(status_file)
                stat = status_path.stat()
            except OSError:
                return
            signature = _d3d11_status_file_signature(stat)
            try:
                payload_text = status_path.read_text(encoding="utf-8")
            except Exception:
                return
            if (
                signature == material_preview_process_state.get("status_signature")
                and payload_text == material_preview_process_state.get("status_payload_text")
            ):
                return
            material_preview_process_state["status_signature"] = signature
            material_preview_process_state["status_payload_text"] = payload_text
            try:
                payload = json.loads(payload_text)
            except Exception:
                return
            if isinstance(payload, Mapping):
                _apply_material_preview_status_payload(payload)

        material_preview_status_timer.timeout.connect(_poll_material_preview_status)
        material_preview_host.native_event_received.connect(
            lambda payload: _apply_material_preview_status_payload(payload)
            if isinstance(payload, Mapping)
            else None
        )

        def _launch_material_preview_package(
            package_dir: Path,
            *,
            reset_view: bool,
            summary: str,
            cleanup_owned_package: bool = True,
        ) -> bool:
            valid_package, missing_paths = self._validate_d3d11_preview_package_paths(package_dir)
            if not valid_package:
                preview_status_label.setText(
                    material_sidecar_text.material_sidecar_package_validation_failed_status(missing_paths)
                )
                if cleanup_owned_package:
                    _remove_material_preview_package(package_dir)
                return False
            status_file = package_dir / "material_values_status.json"
            try:
                status_file.unlink(missing_ok=True)
            except OSError:
                pass
            material_preview_process_state["status_file"] = status_file
            material_preview_process_state["status_signature"] = (0, 0)
            material_preview_process_state["status_payload_text"] = ""
            material_preview_process_state["summary"] = str(summary or "").strip()
            material_preview_process_state["package_dir"] = package_dir
            _configure_material_value_preview_host()
            if cleanup_owned_package and package_dir not in material_preview_packages:
                material_preview_packages.append(package_dir)
            if _material_preview_process_running():
                if material_preview_host.load_package(package_dir, status_file, reset_view=bool(reset_view)):
                    material_preview_host.set_render_tuning(_material_value_preview_render_settings())
                    material_preview_status_timer.start()
                    preview_status_label.setText(
                        material_sidecar_text.material_sidecar_reloading_native_preview_status(summary)
                    )
                    return True
                _stop_material_preview_process()
            try:
                program, arguments = self._native_d3d11_renderer_command(
                    package_dir,
                    status_file,
                    host_widget=material_preview_host,
                    theme_payload=self._archive_isolated_renderer_theme_payload(),
                )
            except Exception as exc:
                preview_status_label.setText(material_sidecar_text.material_sidecar_native_preview_start_failed_status(exc))
                return False
            process = QProcess(dialog)
            process.setProgram(program)
            process.setArguments(arguments)
            process.setProcessChannelMode(QProcess.SeparateChannels)

            def _handle_material_preview_stderr(target: QProcess = process) -> None:
                try:
                    chunk = bytes(target.readAllStandardError()).decode("utf-8", errors="replace").strip()
                except RuntimeError:
                    return
                if chunk:
                    preview_status_label.setText(material_sidecar_text.material_sidecar_native_preview_stderr_status(chunk))

            def _handle_material_preview_error(_error: object, target: QProcess = process) -> None:
                if material_preview_process_state.get("process") is target:
                    preview_status_label.setText(
                        material_sidecar_text.material_sidecar_native_preview_process_error_status(target.errorString())
                    )

            def _handle_material_preview_finished(exit_code: int, _exit_status: object, target: QProcess = process) -> None:
                if material_preview_process_state.get("process") is target:
                    material_preview_process_state["process"] = None
                    if int(exit_code) != 0:
                        preview_status_label.setText(
                            material_sidecar_text.material_sidecar_native_preview_exited_status(exit_code)
                        )
                try:
                    target.deleteLater()
                except RuntimeError:
                    pass

            process.readyReadStandardError.connect(_handle_material_preview_stderr)
            process.errorOccurred.connect(_handle_material_preview_error)
            process.finished.connect(_handle_material_preview_finished)
            material_preview_process_state["process"] = process
            material_preview_status_timer.start()
            preview_status_label.setText(material_sidecar_text.material_sidecar_starting_native_preview_status(summary))
            process.start()
            return True

        def _current_archive_material_preview_result() -> Optional[ArchivePreviewResult]:
            preview_model_entry = preview_model_entry_state.get("entry")
            if not isinstance(preview_model_entry, ArchiveEntry):
                return None
            result = getattr(self, "current_archive_preview_result", None)
            if not isinstance(result, ArchivePreviewResult):
                return None
            preview_model = getattr(result, "preview_model", None)
            if not isinstance(preview_model, ModelPreviewData):
                return None
            if material_preview_entry_key(getattr(preview_model, "path", "")) != material_preview_entry_key(preview_model_entry.path):
                return None
            return result

        def _archive_material_preview_source_package() -> Optional[Path]:
            current_archive_result = _current_archive_material_preview_result()
            if isinstance(current_archive_result, ArchivePreviewResult):
                current_package_text = str(getattr(current_archive_result, "native_preview_package_path", "") or "").strip()
                if current_package_text:
                    return Path(current_package_text)
            try:
                package_dir = getattr(self, "archive_isolated_renderer_active_package", None)
                return Path(package_dir) if package_dir is not None else None
            except (TypeError, ValueError):
                return None

        def _start_material_preview_refresh(*, include_texture_edits: bool, live: bool = False) -> None:
            current_item_for_sync = _current_item()
            if (
                current_item_for_sync is not None
                and selected_value_edit.text() != current_item_for_sync.text(3)
            ):
                _sync_tree_from_selected_value(selected_value_edit.text())
            preview_model_entry = preview_model_entry_state.get("entry")
            if not bool(preview_model_entry_state.get("resolved")):
                preview_status_label.setText(material_sidecar_text.material_sidecar_preview_lookup_pending_status())
                return
            if preview_model_entry is None:
                preview_status_label.setText(material_sidecar_text.material_sidecar_no_preview_model_status())
                return
            if not isinstance(preview_model_entry, ArchiveEntry):
                preview_status_label.setText(material_sidecar_text.material_sidecar_preview_unexpected_entry_status())
                return
            try:
                preview_sidecar_text = _sidecar_text_for_preview(include_texture_edits=include_texture_edits)
            except Exception as exc:
                preview_status_label.setText(material_sidecar_text.material_sidecar_preview_blocked_status(exc))
                return
            if self.worker_thread is not None:
                if live:
                    preview_generation["queued_live"] = True
                    preview_status_label.setText(material_sidecar_text.material_sidecar_live_preview_queued_status())
                else:
                    preview_status_label.setText(material_sidecar_text.material_sidecar_background_task_busy_status())
                return
            all_preview_edits = _edited_values()
            material_preview_edits = _edited_values(material_sidecar_text.material_sidecar_live_preview_kinds())
            texture_edits_active = bool(_edited_values({"texture"}))
            edited_kinds = {row_kind_by_id.get(row_id, "") for row_id in material_preview_edits}
            color_edits_active = "color" in edited_kinds
            material_effects_active = bool(material_preview_edits)
            preview_generation["value"] += 1
            generation = preview_generation["value"]
            companion_entry = self._find_archive_preview_companion_entry(preview_model_entry)
            preview_settings = _material_value_preview_render_settings(material_effects_active=material_effects_active)
            base_cache_key = f"{preview_model_entry.path}|{preview_settings.visible_texture_mode}"
            current_archive_result = _current_archive_material_preview_result()
            reusable_package_dir = (
                _archive_material_preview_source_package()
                if not all_preview_edits
                else None
            )
            fast_source_package_dir = (
                _archive_material_preview_source_package()
                if material_preview_edits and not texture_edits_active
                else None
            )
            cached_base_result = (
                material_preview_base_result_state.get("result")
                if str(material_preview_base_result_state.get("key") or "") == base_cache_key and not texture_edits_active
                else None
            )
            if cached_base_result is None and not texture_edits_active and isinstance(current_archive_result, ArchivePreviewResult):
                cached_base_result = current_archive_result
            preview_status_label.setText(material_sidecar_text.material_sidecar_building_preview_status())

            preview_request = MaterialSidecarPreviewBuildRequest(
                generation=generation,
                preview_model_entry=preview_model_entry,
                sidecar_entry=entry,
                companion_entry=companion_entry,
                preview_sidecar_text=preview_sidecar_text,
                material_preview_edits=dict(material_preview_edits),
                include_texture_edits=include_texture_edits,
                live=bool(live),
                material_effects_active=material_effects_active,
                color_edits_active=color_edits_active,
                preview_settings=preview_settings,
                base_cache_key=base_cache_key,
                reusable_package_dir=reusable_package_dir,
                fast_source_package_dir=fast_source_package_dir,
                current_archive_result=current_archive_result,
                cached_base_result=cached_base_result,
                cache_root=self._native_preview_package_cache_root(),
                texture_entries_by_normalized_path=self.archive_entries_by_normalized_path,
                texture_entries_by_basename=self.archive_entries_by_basename,
                sidecar_entries_by_texture_path=self.archive_sidecar_entries_by_texture_path,
                sidecar_entries_by_texture_basename=self.archive_sidecar_entries_by_texture_basename,
                clone_preview_model=self._clone_archive_preview_model,
                apply_preview_overrides=self._apply_material_sidecar_preview_overrides_to_model,
                texture_resolution_warnings=self._material_sidecar_texture_resolution_warnings,
                label_normalizer=self._normalized_material_preview_label,
                cached_geometry_log=material_sidecar_text.material_sidecar_cached_geometry_log(preview_model_entry.path),
                cached_geometry_note=material_sidecar_text.material_sidecar_cached_geometry_note(),
                building_model_log=material_sidecar_text.material_sidecar_building_model_log(preview_model_entry.path, entry.path),
                prepare_failed_message=material_sidecar_text.material_sidecar_prepare_failed_message(),
            )

            def _task(log: Callable[[str], None], stop_event: threading.Event) -> object:
                return build_material_sidecar_preview(preview_request, log, stop_event)

            def _handle_complete(result: object) -> None:
                if not isinstance(result, MaterialSidecarPreviewBuildResult):
                    preview_status_label.setText(material_sidecar_text.material_sidecar_preview_unexpected_payload_status())
                    return
                result_kind = result.kind
                result_generation = result.generation
                package_dir_object = result.package_dir
                base_result_for_cache = result.base_result_for_cache
                base_result_cache_key = result.base_cache_key
                if int(result_generation) != int(preview_generation["value"]) or not dialog.isVisible():
                    if package_dir_object is not None and result_kind != "reused":
                        _remove_material_preview_package(package_dir_object)
                    return
                if isinstance(base_result_for_cache, ArchivePreviewResult):
                    material_preview_base_result_state["key"] = str(base_result_cache_key or "")
                    material_preview_base_result_state["result"] = base_result_for_cache
                if not isinstance(package_dir_object, (str, Path)):
                    preview_status_label.setText(material_sidecar_text.material_sidecar_no_model_preview_status())
                    return
                package_dir = Path(package_dir_object)
                _configure_material_value_preview_host(material_effects_active=result.material_effects_active)
                summary = material_sidecar_text.material_sidecar_preview_result_summary(
                    str(result_kind),
                    live=result.live,
                    color_edits_active=result.color_edits_active,
                    material_effects_active=result.material_effects_active,
                    elapsed_ms=result.elapsed_ms,
                    batch_count=result.batch_count,
                    vertex_count=result.vertex_count,
                    notes=result.notes,
                    warnings=result.warnings,
                )
                preview_status_label.setText(summary)
                _launch_material_preview_package(
                    package_dir,
                    reset_view=not result.live,
                    summary=summary,
                    cleanup_owned_package=result_kind != "reused",
                )
                if bool(preview_generation.get("queued_live")) and dialog.isVisible():
                    preview_generation["queued_live"] = False
                    live_preview_timer.start()

            self._run_utility_task(
                status_message=material_sidecar_text.material_sidecar_preview_task_status(entry.basename),
                task=_task,
                on_complete=_handle_complete,
                show_archive_progress=True,
                task_accepts_cancel=True,
            )
            preview_generation["worker"] = getattr(self, "utility_worker", None)

        def _schedule_live_preview_for_item(item: Optional[QTreeWidgetItem]) -> None:
            if item is None or preview_model_entry_state.get("entry") is None or not live_preview_checkbox.isChecked():
                if item is not None and live_preview_checkbox.isChecked() and not bool(preview_model_entry_state.get("resolved")):
                    preview_status_label.setText(material_sidecar_text.material_sidecar_live_preview_waiting_status())
                return
            if not material_sidecar_text.material_sidecar_kind_supports_live_preview(item.text(1)):
                preview_status_label.setText(material_sidecar_text.material_sidecar_texture_edit_refresh_status())
                return
            live_preview_timer.start()

        live_preview_timer.timeout.connect(lambda: _start_material_preview_refresh(include_texture_edits=False, live=True))
        selected_value_live_refresh_timer.timeout.connect(
            lambda: _start_material_preview_refresh(include_texture_edits=False, live=True)
        )

        def _queue_selected_value_live_refresh(_text: str) -> None:
            if syncing_selected_value["active"]:
                return
            item = _current_item()
            if (
                item is None
                or not material_sidecar_text.material_sidecar_kind_supports_live_preview(item.text(1))
                or not live_preview_checkbox.isChecked()
            ):
                return
            _record_selected_value_pending_edit(item)
            preview_status_label.setText(material_sidecar_text.material_sidecar_live_preview_scheduled_status())
            if selected_value_ready_for_live_refresh(item.text(1), selected_value_edit.text()):
                preview_status_label.setText(material_sidecar_text.material_sidecar_live_preview_starting_status())
                try:
                    _start_material_preview_refresh(include_texture_edits=False, live=True)
                except Exception as exc:
                    preview_status_label.setText(material_sidecar_text.material_sidecar_live_preview_start_failed_status(exc))
                return
            selected_value_live_refresh_timer.start()

        def _continue_material_sidecar_export(
            request_id: int,
            preparation: MaterialSidecarExportPreparation,
        ) -> None:
            if request_id != int(getattr(self, "_material_sidecar_export_request_id", 0) or 0):
                return
            if not dialog.isVisible():
                return
            selected_related_entries = self._prompt_material_sidecar_related_files(
                preparation.related_files,
                edited_entry=entry,
            )
            if selected_related_entries is None:
                return
            target = self._collect_archive_mod_ready_export_target(
                browse_title=material_sidecar_text.material_sidecar_export_target_title(),
                prompt_for_metadata=True,
                dialog_title=material_sidecar_text.material_sidecar_export_target_title(),
            )
            if target is None:
                return
            export_root, package_info, create_no_encrypt_file, _include_related_files, export_options = target

            def _task(log: Callable[[str], None], stop_event: threading.Event) -> object:
                return export_material_sidecar_mod_package(
                    edited_entry=entry,
                    edited_text=preparation.edit_result.text,
                    related_entries=selected_related_entries,
                    parent_root=export_root,
                    package_info=package_info,
                    export_options=export_options,
                    create_no_encrypt_file=create_no_encrypt_file,
                    read_entry_bytes=lambda archive_entry: read_archive_entry_data(
                        archive_entry,
                        stop_event=stop_event,
                    )[0],
                    on_log=log,
                    stop_event=stop_event,
                )

            def _handle_complete(result: object) -> None:
                if request_id != int(getattr(self, "_material_sidecar_export_request_id", 0) or 0):
                    return
                package_root = getattr(result, "package_root", None)
                if not isinstance(package_root, Path):
                    self.set_status_message(material_sidecar_text.material_sidecar_unexpected_export_payload_status(), error=True)
                    return
                title, message = material_sidecar_text.material_sidecar_export_complete_dialog_text(package_root)
                QMessageBox.information(dialog, title, message)
                self.set_status_message(material_sidecar_text.material_sidecar_export_complete_status(package_root))

            self._run_utility_task_when_idle(
                status_message=material_sidecar_text.material_sidecar_export_task_status(entry.basename),
                task=_task,
                on_complete=_handle_complete,
                show_archive_progress=True,
                task_accepts_cancel=True,
            )

        def _handle_material_sidecar_export_prepared(request_id: int, result: object) -> None:
            if request_id != int(getattr(self, "_material_sidecar_export_request_id", 0) or 0):
                return
            if not isinstance(result, MaterialSidecarExportPreparation):
                self.set_status_message("Material sidecar export preparation returned invalid data.", error=True)
                return
            self._run_when_background_idle(
                lambda: _continue_material_sidecar_export(request_id, result),
                label="opening the material sidecar export options",
            )

        def _export() -> None:
            edited_values = _edited_values()
            if not edited_values:
                title, message = material_sidecar_text.material_sidecar_no_changes_dialog_text()
                QMessageBox.information(dialog, title, message)
                return
            request_id = int(getattr(self, "_material_sidecar_export_request_id", 0) or 0) + 1
            self._material_sidecar_export_request_id = request_id
            references = tuple(self.current_archive_model_texture_references)
            archive_entries_by_basename = self.archive_entries_by_basename
            self._run_utility_task_when_idle(
                status_message=f"Preparing material sidecar export for {entry.basename}...",
                task=lambda _log, stop_event: prepare_material_sidecar_export(
                    entry,
                    original_text,
                    dict(edited_values),
                    references=references,
                    archive_entries_by_basename=archive_entries_by_basename,
                    stop_event=stop_event,
                ),
                on_complete=lambda result: _handle_material_sidecar_export_prepared(
                    request_id,
                    result,
                ),
                task_accepts_cancel=True,
            )

        pick_color_button.clicked.connect(_pick_color)
        reset_button.clicked.connect(_reset_selected)
        show_preview_button.clicked.connect(lambda _checked=False: _start_material_preview_refresh(include_texture_edits=True, live=False))
        refresh_preview_button.clicked.connect(lambda _checked=False: _start_material_preview_refresh(include_texture_edits=True, live=False))
        material_preview_settings_button.clicked.connect(
            lambda _checked=False, parent_dialog=dialog: self._open_modal_model_preview_settings_dialog(parent_dialog)
        )
        export_button.clicked.connect(_export)
        close_button.clicked.connect(dialog.accept)
        tree.currentItemChanged.connect(lambda _current, _previous: _sync_selected_value_from_tree())
        tree.itemChanged.connect(_handle_material_tree_item_changed)
        selected_value_edit.textChanged.connect(_sync_tree_from_selected_value)
        selected_value_edit.textChanged.connect(_queue_selected_value_live_refresh)
        dialog.finished.connect(lambda _result=0: _shutdown_material_preview())
        _sync_selected_value_from_tree()
        QTimer.singleShot(material_sidecar_text.material_sidecar_initial_lookup_delay_ms(), _resolve_material_preview_model_entry)
        dialog.exec()


__all__ = ["ArchiveMaterialSidecarEditorMixin"]
