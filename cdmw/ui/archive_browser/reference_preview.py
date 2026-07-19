"""Archive referenced-file preview and reference action controls."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import Dict, Optional

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.archive_browser.actions import archive_context_menu_icons
from cdmw.constants import DEFAULT_UI_PREVIEW_COLOR_SCHEME
from cdmw.domain.archives.filters import archive_entry_identity_key
from cdmw.services.archive_query_service import build_archive_asset_family_graph
from cdmw.services.archive_read_service import build_archive_entry_metadata_summary
from cdmw.services.archive_preview_service import build_archive_preview_result
from cdmw.services.material_sidecar_service import is_material_sidecar_entry
from cdmw.models import ArchiveEntry, ArchivePreviewResult
from cdmw.services.preview_rendering_service import (
    NativePreviewCoreAttempt,
    run_native_preview_core_preview_job,
)
from cdmw.ui.model_preview_native import ARCHIVE_MODEL_RENDERER_D3D11
from cdmw.ui.native_d3d11_preview_host import NativeD3D11PreviewHostFrame
from cdmw.ui.shell.theme_controller import build_monospace_font, read_log_text_style, read_text_color_scheme
from cdmw.ui.widgets import (
    ArchiveDetailsEditor,
    CodePreviewEditor,
    MediaPreviewWidget,
    NativePreviewPanel,
    PreviewLabel,
    PreviewScrollArea,
)
from cdmw.workers.archive_preview_native import NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS


class ArchiveReferencePreviewMixin:
    """Referenced asset preview, D3D11 reference preview, and reference actions."""
    def _current_archive_preview_result_for_reference_entry(
        self,
        entry: ArchiveEntry,
    ) -> Optional[ArchivePreviewResult]:
        current_entry = self._current_archive_entry()
        result = getattr(self, "current_archive_preview_result", None)
        if (
            not isinstance(current_entry, ArchiveEntry)
            or not isinstance(result, ArchivePreviewResult)
            or bool(getattr(self, "archive_preview_showing_loose", False))
        ):
            return None
        if archive_entry_identity_key(current_entry) != archive_entry_identity_key(entry):
            return None
        return result

    def _show_archive_reference_preview_dialog(
        self,
        entry: ArchiveEntry,
        result: ArchivePreviewResult,
    ) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Referenced File Preview - {entry.basename}")
        dialog.setModal(True)
        dialog.resize(1040, 760)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title_label = QLabel(result.title or entry.basename)
        title_label.setObjectName("SectionTitle")
        layout.addWidget(title_label)

        meta_label = QLabel(result.metadata_summary or build_archive_entry_metadata_summary(entry))
        meta_label.setWordWrap(True)
        meta_label.setObjectName("HintLabel")
        layout.addWidget(meta_label)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        export_button = QPushButton("Export DDS..." if entry.extension == ".dds" else "Export...")
        action_row.addWidget(export_button)
        open_in_editor_button: Optional[QPushButton] = None
        if entry.extension == ".dds":
            open_in_editor_button = QPushButton("Open In Texture Editor...")
            action_row.addWidget(open_in_editor_button)
        edit_hkx_button: Optional[QPushButton] = None
        if str(entry.extension or "").lower() in {".hkx", ".hkt"}:
            edit_hkx_button = QPushButton("Edit HKX...")
            action_row.addWidget(edit_hkx_button)
        pending_hkx_editor_entry: Dict[str, ArchiveEntry] = {}
        native_reference_package_path = str(getattr(result, "native_preview_package_path", "") or "").strip()
        preview_dialog_settings_button = QPushButton("Preview Settings...")
        preview_dialog_settings_button.setToolTip("Open the global preview settings used by every model preview window.")
        preview_dialog_settings_button.setVisible(
            result.preferred_view == "model"
            and (result.preview_model is not None or bool(native_reference_package_path))
        )
        action_row.addWidget(preview_dialog_settings_button)
        action_row.addStretch(1)
        close_button = QPushButton("Close")
        close_button.setDefault(True)
        action_row.addWidget(close_button)
        layout.addLayout(action_row)

        preview_tabs = QTabWidget()
        preview_stack = QStackedWidget()
        preview_label = PreviewLabel("No image preview available.")
        preview_scroll = PreviewScrollArea()
        preview_scroll.setWidgetResizable(False)
        preview_scroll.setAlignment(Qt.AlignCenter)
        preview_scroll.setWidget(preview_label)
        preview_label.attach_scroll_area(preview_scroll)
        dialog_font = build_monospace_font(self.settings)
        dialog_highlight_style = read_log_text_style(self.settings)
        preview_color_scheme = read_text_color_scheme(
            self.settings,
            "appearance/preview_color_scheme",
            DEFAULT_UI_PREVIEW_COLOR_SCHEME,
        )
        preview_text_edit = CodePreviewEditor(
            theme_key=self.current_theme_key,
            highlight_style=dialog_highlight_style,
            color_scheme=preview_color_scheme,
        )
        preview_text_edit.document().setMaximumBlockCount(5000)
        preview_summary_edit = ArchiveDetailsEditor(
            theme_key=self.current_theme_key,
            highlight_style=dialog_highlight_style,
            color_scheme=preview_color_scheme,
        )
        preview_summary_edit.document().setMaximumBlockCount(5000)
        preview_info_edit = ArchiveDetailsEditor(
            theme_key=self.current_theme_key,
            highlight_style=dialog_highlight_style,
            color_scheme=preview_color_scheme,
        )
        preview_info_edit.document().setMaximumBlockCount(2000)
        preview_text_edit.apply_font_preferences(dialog_font, preserve_size=False)
        preview_text_edit.set_highlight_style(dialog_highlight_style)
        preview_text_edit.set_color_scheme(preview_color_scheme)
        preview_summary_edit.apply_font_preferences(dialog_font, preserve_size=False)
        preview_summary_edit.set_highlight_style(dialog_highlight_style)
        preview_summary_edit.set_color_scheme(preview_color_scheme)
        preview_info_edit.apply_font_preferences(dialog_font, preserve_size=False)
        preview_info_edit.set_highlight_style(dialog_highlight_style)
        preview_info_edit.set_color_scheme(preview_color_scheme)
        preview_model = NativePreviewPanel("No model preview available.", theme_key=self.current_theme_key)
        self._configure_model_preview_widget(preview_model, apply_toggle_defaults=True)
        preview_d3d11_host = NativeD3D11PreviewHostFrame(dialog)
        preview_d3d11_host.setMinimumSize(320, 240)
        preview_media = MediaPreviewWidget("No media preview available.", theme_key=self.current_theme_key)
        preview_stack.addWidget(preview_scroll)
        preview_stack.addWidget(preview_model)
        preview_stack.addWidget(preview_d3d11_host)
        preview_stack.addWidget(preview_media)
        preview_stack.addWidget(preview_text_edit)
        preview_stack.addWidget(preview_summary_edit)
        preview_stack.addWidget(preview_info_edit)

        preview_tab = QWidget()
        preview_tab_layout = QVBoxLayout(preview_tab)
        preview_tab_layout.setContentsMargins(0, 0, 0, 0)
        preview_tab_layout.setSpacing(6)
        preview_text_tools = self._build_archive_text_tools(preview_text_edit)
        preview_summary_tools = self._build_archive_text_tools(preview_summary_edit)
        preview_info_tools = self._build_archive_text_tools(preview_info_edit)
        preview_controls_hint_label = QLabel(
            "Controls: left-drag orbit | middle/right-drag pan | Shift+left-drag pan | mouse wheel zoom | Fit resets view."
        )
        preview_controls_hint_label.setObjectName("HintLabel")
        preview_controls_hint_label.setWordWrap(True)
        preview_controls_hint_label.setToolTip(
            "These controls move the preview camera/view only. Mesh placement and exported transforms are changed in edit/alignment tools."
        )
        reference_preview_text_tools = {
            preview_text_edit: preview_text_tools,
            preview_summary_edit: preview_summary_tools,
            preview_info_edit: preview_info_tools,
        }

        def _update_reference_preview_text_tools_visibility(*_args) -> None:
            current_widget = preview_stack.currentWidget()
            for editor, tools in reference_preview_text_tools.items():
                tools.setVisible(current_widget is editor)
            preview_controls_hint_label.setVisible(current_widget is preview_model or current_widget is preview_d3d11_host)

        preview_tab_layout.addWidget(preview_text_tools)
        preview_tab_layout.addWidget(preview_summary_tools)
        preview_tab_layout.addWidget(preview_info_tools)
        preview_tab_layout.addWidget(preview_stack)
        preview_tab_layout.addWidget(preview_controls_hint_label)
        preview_stack.currentChanged.connect(_update_reference_preview_text_tools_visibility)

        details_edit = ArchiveDetailsEditor(
            theme_key=self.current_theme_key,
            highlight_style=dialog_highlight_style,
            color_scheme=preview_color_scheme,
        )
        details_edit.document().setMaximumBlockCount(2000)
        details_edit.apply_font_preferences(dialog_font, preserve_size=False)
        details_edit.set_color_scheme(preview_color_scheme)
        base_detail_text = result.detail_text or result.metadata_summary or "No details available."

        def _update_preview_dialog_details(_debug_text: str = "") -> None:
            details_edit.setPlainText(
                self._compose_model_preview_detail_text(
                    base_detail_text,
                    preview_model.debug_details_text(),
                )
            )

        preview_model.debug_details_changed.connect(_update_preview_dialog_details)
        _update_preview_dialog_details()

        details_tab = QWidget()
        details_tab_layout = QVBoxLayout(details_tab)
        details_tab_layout.setContentsMargins(0, 0, 0, 0)
        details_tab_layout.setSpacing(6)
        details_tab_layout.addWidget(self._build_archive_text_tools(details_edit))
        details_tab_layout.addWidget(details_edit)

        preview_tabs.addTab(preview_tab, "Preview")
        reference_family_graph = result.asset_family_graph
        if reference_family_graph is None and result.model_texture_references:
            reference_family_graph = build_archive_asset_family_graph(entry, result.model_texture_references)
        if reference_family_graph is not None and tuple(getattr(reference_family_graph, "member_rows", ()) or ()):
            family_tab = QWidget()
            family_layout = QVBoxLayout(family_tab)
            family_layout.setContentsMargins(0, 0, 0, 0)
            family_layout.setSpacing(6)
            family_summary = QLabel(str(getattr(reference_family_graph, "summary", "") or "Recovered asset family relationships."))
            family_summary.setObjectName("HintLabel")
            family_summary.setWordWrap(True)
            family_layout.addWidget(family_summary)
            family_tree = QTreeWidget()
            family_tree.setColumnCount(5)
            family_tree.setHeaderLabels(["Role", "File", "Status", "Evidence", "Why"])
            family_tree.setRootIsDecorated(True)
            family_tree.setAlternatingRowColors(True)
            family_tree.setUniformRowHeights(True)
            family_tree.setSelectionMode(QAbstractItemView.SingleSelection)
            self._install_tree_horizontal_wheel_guard(family_tree)
            family_groups: Dict[str, QTreeWidgetItem] = {}
            for member in tuple(getattr(reference_family_graph, "member_rows", ()) or ()):
                group_item = family_groups.get(member.group)
                if group_item is None:
                    group_item = QTreeWidgetItem([member.group, "", "", "", ""])
                    group_item.setFlags(Qt.ItemIsEnabled)
                    group_item.setExpanded(True)
                    family_tree.addTopLevelItem(group_item)
                    family_groups[member.group] = group_item
                child = QTreeWidgetItem(
                    [
                        str(member.role or "Related File"),
                        str(member.display_name or PurePosixPath(str(member.path or "").replace("\\", "/")).name or "-"),
                        str(member.status or "-"),
                        str(member.source_evidence or member.confidence or "-"),
                        str(member.reason or "Recovered relationship evidence."),
                    ]
                )
                child.setToolTip(1, str(member.path or ""))
                child.setToolTip(4, str(member.warning or member.reason or ""))
                self._style_archive_role_columns(child, str(member.role or member.group), 0, 1)
                self._ui_style_status_columns(child, {2: member.status, 3: member.source_evidence or member.confidence, 4: member.reason})
                group_item.addChild(child)
            for group_item in family_groups.values():
                group_item.setText(0, f"{group_item.text(0)} ({group_item.childCount()})")
            family_tree.expandAll()
            family_layout.addWidget(family_tree, stretch=1)
            preview_tabs.addTab(family_tab, "Asset Family")
        preview_tabs.addTab(details_tab, "Details")
        layout.addWidget(preview_tabs, stretch=1)

        def _preview_text_looks_like_structured_summary(preview_text: str) -> bool:
            stripped = str(preview_text or "").lstrip("\ufeff\r\n\t ")
            if stripped.startswith(("<?xml", "<", "{", "[")):
                return False
            sample = stripped[:4096]
            return any(
                marker in sample
                for marker in (
                    "Simplified values for ",
                    "What this appears to contain:",
                    "Recognized fields:",
                    "HKX tagfile preview for ",
                    "Format summary:",
                    "Tag item map:",
                    "Detected classes/types:",
                    "Entry Metadata",
                    "Preview / Texture Notes",
                    "Binary Header Preview",
                    "Prefab evidence",
                )
            )

        reference_d3d11_process: Optional[QProcess] = None

        def _append_reference_d3d11_status(message: str) -> None:
            detail = str(message or "").strip()
            if not detail:
                return
            current = preview_info_edit.toPlainText().strip()
            preview_info_edit.setPlainText(f"{current}\n\n{detail}".strip() if current else detail)

        def _start_reference_d3d11_preview() -> None:
            nonlocal reference_d3d11_process
            package_text = str(native_reference_package_path or "").strip()
            if not package_text or reference_d3d11_process is not None:
                return
            package_dir = Path(package_text)
            status_file = package_dir / "reference_d3d11_status.json"
            try:
                program, arguments = self._native_d3d11_renderer_command(
                    package_dir,
                    status_file,
                    host_widget=preview_d3d11_host,
                    theme_payload=self._archive_isolated_renderer_theme_payload(),
                )
            except Exception as exc:
                _append_reference_d3d11_status(
                    f"Native D3D11 reference preview could not start: {exc}"
                )
                preview_stack.setCurrentWidget(preview_info_edit)
                _update_reference_preview_text_tools_visibility()
                return
            process = QProcess(dialog)
            process.setProgram(program)
            process.setArguments(arguments)
            process.setProcessChannelMode(QProcess.MergedChannels)

            def _handle_process_error(_error: object) -> None:
                _append_reference_d3d11_status(
                    f"Native D3D11 reference preview process error: {process.errorString()}"
                )

            def _handle_process_finished(exit_code: int, _exit_status: object) -> None:
                if exit_code != 0:
                    _append_reference_d3d11_status(
                        f"Native D3D11 reference preview exited with code {exit_code}."
                    )

            process.errorOccurred.connect(_handle_process_error)
            process.finished.connect(_handle_process_finished)
            reference_d3d11_process = process
            process.start()

        def _stop_reference_d3d11_preview() -> None:
            process = reference_d3d11_process
            if process is None:
                return
            def _kill_reference_process_later() -> None:
                try:
                    if process.state() != QProcess.NotRunning:
                        process.kill()
                except RuntimeError:
                    pass
            try:
                if process.state() != QProcess.NotRunning:
                    process.terminate()
                    QTimer.singleShot(750, _kill_reference_process_later)
            except RuntimeError:
                pass

        dialog.finished.connect(lambda _result: _stop_reference_d3d11_preview())

        preferred_view = result.preferred_view
        if preferred_view == "image" and (result.preview_image is not None or result.preview_image_path):
            if result.preview_image is not None:
                preview_label.set_preview_image(result.preview_image, result.title or entry.basename)
            else:
                preview_label.set_preview_image_path(result.preview_image_path, result.title or entry.basename)
            preview_media.clear_media("No media preview available.")
            preview_model.clear_model("No model preview available.")
            preview_stack.setCurrentWidget(preview_scroll)
        elif preferred_view == "model" and result.preview_model is not None:
            preview_model.set_model(result.preview_model)
            if str(entry.extension or "").lower() in {".hkx", ".hkt"}:
                try:
                    preview_model.set_render_settings(
                        dataclasses.replace(
                            preview_model.render_settings(),
                            show_physics_overlay=True,
                            show_physics_simulation_preview=False,
                        )
                    )
                except Exception:
                    pass
            preview_label.clear_preview("No image preview available.")
            preview_media.clear_media("No media preview available.")
            preview_stack.setCurrentWidget(preview_model)
        elif preferred_view == "model" and native_reference_package_path:
            preview_label.clear_preview("No image preview available.")
            preview_model.clear_model("No model preview available.")
            preview_media.clear_media("No media preview available.")
            preview_stack.setCurrentWidget(preview_d3d11_host)
            QTimer.singleShot(0, _start_reference_d3d11_preview)
        elif preferred_view == "media" and result.preview_media_path:
            preview_label.clear_preview("No image preview available.")
            preview_model.clear_model("No model preview available.")
            preview_media.set_media(
                result.preview_media_path,
                media_kind=result.preview_media_kind,
                detail_text=result.detail_text or result.metadata_summary,
            )
            preview_stack.setCurrentWidget(preview_media)
        elif preferred_view == "text":
            preview_text = result.preview_text or "No text preview available."
            preview_text_edit.set_language_for_extension(
                self._archive_preview_text_language_extension_for_entry(entry, preview_text)
            )
            if _preview_text_looks_like_structured_summary(preview_text):
                preview_summary_edit.setPlainText(preview_text)
                preview_stack.setCurrentWidget(preview_summary_edit)
            else:
                preview_text_edit.setPlainText(preview_text)
                preview_stack.setCurrentWidget(preview_text_edit)
            preview_label.clear_preview("No image preview available.")
            preview_model.clear_model("No model preview available.")
            preview_media.clear_media("No media preview available.")
        else:
            preview_info_edit.setPlainText(result.detail_text or result.metadata_summary or "No preview available.")
            preview_label.clear_preview("No image preview available.")
            preview_model.clear_model("No model preview available.")
            preview_media.clear_media("No media preview available.")
            preview_stack.setCurrentWidget(preview_info_edit)
        _update_reference_preview_text_tools_visibility()

        export_button.clicked.connect(
            lambda _checked=False, current_entry=entry: self._export_archive_reference_entry(current_entry)
        )
        if open_in_editor_button is not None:
            open_in_editor_button.clicked.connect(
                lambda _checked=False, current_entry=entry: self._open_archive_entry_in_texture_editor(current_entry)
            )
        if edit_hkx_button is not None:
            def _open_hkx_editor_from_reference_preview(
                _checked: bool = False,
                current_entry: ArchiveEntry = entry,
            ) -> None:
                pending_hkx_editor_entry["entry"] = current_entry
                dialog.accept()

            edit_hkx_button.clicked.connect(_open_hkx_editor_from_reference_preview)
        preview_dialog_settings_button.clicked.connect(
            lambda _checked=False, parent_dialog=dialog: self._open_modal_model_preview_settings_dialog(parent_dialog)
        )
        close_button.clicked.connect(dialog.accept)
        dialog.exec()
        pending_entry = pending_hkx_editor_entry.get("entry")
        if isinstance(pending_entry, ArchiveEntry):
            QTimer.singleShot(
                0,
                lambda current_entry=pending_entry: self._edit_archive_hkx_entry_when_idle(current_entry),
            )

    def _update_archive_texture_reference_action_controls(self) -> None:
        controls_enabled = self.worker_thread is None
        family_reason = (
            "wait for the current background task to finish"
            if not controls_enabled
            else "open a file with recovered Asset Family relationships first"
        )
        has_family = self._archive_has_asset_family_workspace()
        self.archive_asset_family_button.setVisible(has_family)
        self._set_action_button_state(
            self.archive_asset_family_button,
            controls_enabled and has_family,
            "Open the recovered file family for this selection: model, material, textures, HKX, meshinfo, prefab, rig, and animation links.",
            family_reason,
        )

    def _show_archive_texture_reference_context_menu(self, position) -> None:
        sender = self.sender()
        tree = sender if isinstance(sender, QTreeWidget) else self.archive_texture_refs_tree
        item = tree.itemAt(position)
        if item is None:
            return
        if self._archive_reference_from_item(item) is None:
            return
        if not item.isSelected():
            tree.setCurrentItem(item)
            tree.clearSelection()
            item.setSelected(True)

        selected_references = self._selected_archive_texture_references()
        selected_entries = self._resolved_archive_reference_entries(selected_references)
        single_selected_entry = selected_entries[0] if len(selected_entries) == 1 else None
        menu = QMenu(self)
        if hasattr(menu, "setToolTipsVisible"):
            menu.setToolTipsVisible(True)
        menu_icons = archive_context_menu_icons()

        def _add_section(kind: str, label: str) -> None:
            menu.addSection(menu_icons[kind], label)

        def _add_action(kind: str, label: str, callback, tooltip: str = ""):
            action = menu.addAction(menu_icons[kind], label)
            if tooltip:
                action.setToolTip(tooltip)
                action.setStatusTip(tooltip)
            action.triggered.connect(callback)
            return action

        if isinstance(single_selected_entry, ArchiveEntry):
            _add_section("view", "View + Inspect")
            _add_action(
                "view",
                "Open Preview",
                lambda _checked=False: self._open_selected_archive_texture_reference(),
                "Open the selected Asset Family row in a referenced-file preview window.",
            )
            if str(single_selected_entry.extension or "").lower() in {".hkx", ".hkt"}:
                _add_section("physics", "Physics / HKX")
                _add_action(
                    "physics",
                    "Edit HKX...",
                    lambda _checked=False: self._edit_selected_archive_hkx_reference(),
                    "Edit the selected Asset Family row as an HKX/HKT physics file.",
                )
            if str(single_selected_entry.extension or "").lower() == ".dds":
                _add_section("texture", "Texture")
                _add_action(
                    "texture",
                    "Open In Texture Editor...",
                    lambda _checked=False, current_entry=single_selected_entry: self._open_archive_entry_in_texture_editor(current_entry),
                    "Open the selected DDS row in Texture Editor.",
                )
            if is_material_sidecar_entry(single_selected_entry):
                _add_section("texture", "Material")
                _add_action(
                    "texture",
                    "Edit Material Values...",
                    lambda _checked=False: self._edit_selected_archive_material_sidecar_reference(),
                    "Edit the selected Asset Family row as a material sidecar.",
                )
        if selected_entries:
            _add_section("file", "Selection")
            _add_action(
                "file",
                "Show Selected In Browser",
                lambda _checked=False: self._scope_selected_archive_texture_references(),
                "Filter Archive Files to the selected resolved Asset Family rows.",
            )
            _add_action(
                "file",
                "Export Selected...",
                lambda _checked=False: self._export_selected_archive_texture_reference(),
                "Export the selected resolved Asset Family rows to a folder.",
            )
        all_entries = self._current_archive_asset_set_entries(include_hints=False)
        if all_entries:
            _add_section("family", "Asset Family")
            _add_action(
                "family",
                "Filter to Family",
                lambda _checked=False: self._scope_current_archive_asset_set(include_hints=False),
                "Filter Archive Files to the required/recommended files in this Asset Family.",
            )
            if any(str(getattr(row, "include_policy", "") or "").casefold() == "manual" for row in self.current_archive_family_member_rows):
                _add_action(
                    "family",
                    "Show Family + Hints",
                    lambda _checked=False: self._scope_current_archive_asset_set(include_hints=True),
                )
            if self.current_archive_used_by_references:
                _add_action(
                    "family",
                    "Show Family + Used By",
                    lambda _checked=False: self._scope_current_archive_asset_set(include_used_by=True),
                )
            _add_action(
                "family",
                "Export Family...",
                lambda _checked=False: self._export_current_archive_asset_set(),
                "Choose which required/recommended Asset Family files to export, with optional hints.",
            )
            _add_section("file", "Export")
            _add_action(
                "file",
                "Export Raw References...",
                lambda _checked=False: self._export_all_archive_texture_references(),
                "Export every resolved raw referenced-file row. Use Export Family for the curated Asset Family package.",
            )
        if not menu.isEmpty():
            menu.exec(tree.viewport().mapToGlobal(position))

    def _open_selected_archive_texture_reference(self) -> None:
        selected_references = self._selected_archive_texture_references()
        reference = selected_references[0] if len(selected_references) == 1 else self._current_archive_texture_reference()
        resolved_entry = getattr(reference, "resolved_entry", None) if reference is not None else None
        if not isinstance(resolved_entry, ArchiveEntry):
            self.set_status_message("Select a resolved referenced file first.", error=True)
            return
        semantic_sidecar_texts = tuple(
            str(text or "") for text in getattr(reference, "sidecar_texts", ()) if str(text or "").strip()
        ) if reference is not None else ()
        self._open_archive_reference_preview_entry(resolved_entry, semantic_sidecar_texts=semantic_sidecar_texts)

    def _open_archive_reference_preview_entry(
        self,
        entry: ArchiveEntry,
        *,
        semantic_sidecar_texts: Sequence[str] = (),
    ) -> None:
        resolved_entry = entry
        current_result = self._current_archive_preview_result_for_reference_entry(resolved_entry)
        if current_result is not None:
            self._show_archive_reference_preview_dialog(resolved_entry, current_result)
            self.set_status_message(f"Opened preview for {resolved_entry.basename}.")
            return
        remote_dependencies = None
        remote_bridge = getattr(self, "archive_remote_bridge", None)
        if remote_bridge is not None and remote_bridge.displays_v2:
            remote_dependencies = remote_bridge.prepared_dependencies_for(resolved_entry)
            if remote_dependencies is None:
                self.set_status_message(
                    "Referenced preview dependencies are no longer available; select the source asset again.",
                    error=True,
                )
                return
        dependency_entries = remote_dependencies.entries if remote_dependencies is not None else ()
        companion_entry = self._find_archive_preview_companion_entry(
            resolved_entry,
            entries_by_normalized_path=(
                remote_dependencies.entries_by_normalized_path
                if remote_dependencies is not None
                else None
            ),
        )

        def _task(log: Callable[[str], None]) -> ArchivePreviewResult:
            log(f"Preparing referenced-file preview for {resolved_entry.path}...")
            preview_settings = self._current_model_preview_render_settings()
            if (
                self._archive_model_renderer_backend() == ARCHIVE_MODEL_RENDERER_D3D11
                and str(getattr(resolved_entry, "extension", "") or "").strip().lower() in NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS
            ):
                try:
                    native_attempt = run_native_preview_core_preview_job(
                        resolved_entry,
                        cache_root=self.archive_cache_root / "native_preview_core",
                        render_settings=preview_settings,
                        companion_entry=companion_entry,
                        dependency_entries=dependency_entries,
                        dependency_entries_complete=remote_dependencies is not None,
                        package_root=(
                            Path(self.archive_package_root_edit.text().strip()).expanduser()
                            if self.archive_package_root_edit.text().strip()
                            else None
                        ),
                        timeout_seconds=8.0,
                    )
                except Exception as exc:
                    native_attempt = NativePreviewCoreAttempt(
                        status="error",
                        fallback_reason=f"reference native preview-core failed: {exc}",
                    )
                native_line = native_attempt.diagnostic_line()
                if native_attempt.succeeded:
                    diagnostics = dict(native_attempt.diagnostics)
                    notes = tuple(str(note) for note in tuple(diagnostics.get("notes", ()) or ()) if str(note).strip())
                    native_detail_lines = [
                        "Native Preview Core generated a D3D11 preview package without Python mesh preparation.",
                        "D3D11 package source: native-core",
                        native_line,
                    ]
                    if notes:
                        native_detail_lines.append("Native Material Notes: " + "; ".join(notes[:8]))
                    detail_text = "\n".join(part for part in native_detail_lines if part)
                    return ArchivePreviewResult(
                        status="ok",
                        title=resolved_entry.basename,
                        metadata_summary=f"{build_archive_entry_metadata_summary(resolved_entry)} | native preview package",
                        detail_text=detail_text,
                        preview_model=None,
                        asset_family_graph=build_archive_asset_family_graph(resolved_entry, ()),
                        native_preview_package_path=native_attempt.package_path,
                        native_preview_diagnostics=diagnostics,
                        preferred_view="model",
                    )
                return ArchivePreviewResult(
                    status="error",
                    title=resolved_entry.basename,
                    metadata_summary=build_archive_entry_metadata_summary(resolved_entry),
                    detail_text="\n".join(
                        part
                        for part in (
                            "Native Preview Core did not generate a D3D11 package.",
                            "D3D11 referenced-file preview is native-only; Python mesh preparation was skipped.",
                            native_line,
                            f"Native failure reason: {native_attempt.fallback_reason}",
                        )
                        if part
                    ),
                    native_preview_diagnostics=dict(native_attempt.diagnostics),
                    preferred_view="details",
                )
            result = build_archive_preview_result(
                resolved_entry,
                texture_entries_by_normalized_path=self.archive_entries_by_normalized_path,
                texture_entries_by_basename=self.archive_entries_by_basename,
                sidecar_entries_by_texture_path=self.archive_sidecar_entries_by_texture_path,
                sidecar_entries_by_texture_basename=self.archive_sidecar_entries_by_texture_basename,
                semantic_sidecar_texts=semantic_sidecar_texts,
                visible_texture_mode=preview_settings.visible_texture_mode,
            )
            return result

        def _handle_complete(result: object) -> None:
            if not isinstance(result, ArchivePreviewResult):
                self.set_status_message("Referenced-file preview finished with an unexpected result payload.", error=True)
                return
            self._show_archive_reference_preview_dialog(resolved_entry, result)
            self.set_status_message(f"Opened preview for {resolved_entry.basename}.")

        self._run_utility_task(
            status_message=f"Preparing preview for {resolved_entry.basename}...",
            task=_task,
            on_complete=_handle_complete,
            show_archive_progress=True,
        )

    def _export_selected_archive_texture_reference(self) -> None:
        selected_entries = self._resolved_archive_reference_entries(self._selected_archive_texture_references())
        if not selected_entries:
            self.set_status_message("Select one or more resolved referenced files first.", error=True)
            return
        self._export_archive_reference_entries_to_folder(
            selected_entries,
            title="Export Selected Referenced Files",
        )

    def _export_all_archive_texture_references(self) -> None:
        resolved_entries = self._resolved_archive_reference_entries(self.current_archive_model_texture_references)
        if not resolved_entries:
            self.set_status_message("No resolved referenced files are available to export.", error=True)
            return
        self._export_archive_reference_entries_to_folder(
            resolved_entries,
            title="Export All Referenced Files",
        )
