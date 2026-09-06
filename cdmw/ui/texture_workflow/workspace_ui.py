"""The shared asset list, mode controls and review surface for a texture job."""

from __future__ import annotations

from collections import deque
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QDialog, QFileDialog,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter, QStackedWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from cdmw.models import TextureEditorSourceBinding
from cdmw.ui.shell.lazy_tool_tab import created_tool_widget
from cdmw.ui.texture_workflow.job import (
    TEXTURE_MODE_SETTING, TEXTURE_TOOL_ALIASES, TextureJobAsset, normalize_texture_mode,
)


class TextureJobUiMixin:
    def _handle_scanned_assets(self, paths) -> None:
        root = Path(self.original_dds_edit.text()).expanduser().resolve()
        for source in paths:
            path = Path(source).resolve()
            if path.is_relative_to(root):
                self.job.add_source(path, TextureEditorSourceBinding(
                    source_path=str(path), original_dds_path=str(path),
                    relative_path=path.relative_to(root).as_posix(),
                ))
        self._refresh_texture_assets()

    def current_compare_path_for_research(self) -> str:
        asset = self.job.assets.get(self.job.active_asset_key)
        return (asset.source_binding.archive_relative_path or asset.source_binding.relative_path) if asset else ""

    def refresh_compare_list(self, *, select_current: bool = False) -> None:
        """Compatibility entry for root changes; populate the shared asset list."""
        del select_current
        if not hasattr(self, "asset_list") or self.shell._background_task_active():
            return
        root_text = self.original_dds_edit.text().strip()
        if not root_text:
            return
        root = Path(root_text).expanduser()
        def collect(_on_log):
            from cdmw.services.texture_workflow_service import collect_dds_files
            return collect_dds_files(root, ()) if root.is_dir() else []
        def receive(paths):
            if self.original_dds_edit.text().strip() != root_text:
                return
            for path in paths:
                path = Path(path)
                binding = TextureEditorSourceBinding(
                    source_path=str(path), original_dds_path=str(path),
                    relative_path=path.relative_to(root).as_posix(),
                )
                self.job.add_source(path, binding)
            self._refresh_texture_assets()
        self.shell._run_utility_task(status_message="Finding textures...", task=collect, on_complete=receive)

    def build_job_ui(self, editor, recolor, matcher) -> None:
        self.editor_container = editor
        self.recolor_container = recolor
        self.matcher_container = matcher
        self._pending_texture_sources = deque()
        self._syncing_texture_assets = False
        self._review_dialog = None
        self._editor_controls = None
        self._recolor_controls = None
        self.job.mode = normalize_texture_mode(self.shell.settings.value(TEXTURE_MODE_SETTING, "edit"))
        self.setObjectName("TexturesWorkspace")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)
        toolbar = QHBoxLayout()
        self.mode_buttons = {}
        self.mode_button_group = QButtonGroup(self)
        self.mode_button_group.setExclusive(True)
        for key, label in (("edit", "Edit"), ("recolor", "Recolor"), ("upscale", "Upscale")):
            button = QPushButton()
            button.setText(label)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, mode=key: self.set_texture_mode(mode))
            self.mode_button_group.addButton(button)
            self.mode_buttons[key] = button
            toolbar.addWidget(button)
        self.add_texture_button = QPushButton("Add Textures")
        self.add_texture_button.clicked.connect(self._choose_texture_sources)
        self.add_mod_button = QPushButton("Add Mod")
        self.add_mod_button.clicked.connect(self._choose_texture_mod)
        toolbar.addWidget(self.add_texture_button)
        toolbar.addWidget(self.add_mod_button)
        toolbar.addStretch(1)
        self.review_export_button = QPushButton("Review && Export")
        self.review_export_button.clicked.connect(self.show_texture_review)
        toolbar.addWidget(self.review_export_button)
        layout.addLayout(toolbar)

        self.job_splitter = QSplitter(Qt.Horizontal)
        self.job_splitter.setChildrenCollapsible(False)
        sidebar = QWidget()
        sidebar.setMinimumWidth(250)
        sidebar.setMaximumWidth(460)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(0, 0, 0, 0)
        self.asset_search = QLineEdit()
        self.asset_search.setPlaceholderText("Filter textures and material targets")
        self.asset_search.textChanged.connect(self._filter_texture_assets)
        side_layout.addWidget(self.asset_search)
        self.asset_list = QTreeWidget()
        self.asset_list.setObjectName("TextureJobAssets")
        self.asset_list.setHeaderLabels(["Asset", "Target"])
        self.asset_list.setRootIsDecorated(False)
        self.asset_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.asset_list.setMinimumHeight(110)
        self.asset_list.setMaximumHeight(260)
        self.asset_list.currentItemChanged.connect(self._select_texture_asset)
        self.asset_list.itemChanged.connect(self._change_texture_selection)
        side_layout.addWidget(self.asset_list, stretch=1)
        self.remove_texture_button = QPushButton("Remove")
        self.remove_texture_button.setToolTip("Remove the active asset from this texture job.")
        self.remove_texture_button.clicked.connect(self._remove_texture_asset)
        side_layout.addWidget(self.remove_texture_button)
        self.mode_controls = QStackedWidget()
        self.mode_controls.addWidget(QLabel("Opening texture controls..."))
        self.mode_controls.addWidget(self.upscale_controls)
        # Keep lazy content in its page: publication shows the child even if
        # another mode became active while it was loading.
        self.mode_controls.addWidget(recolor)
        side_layout.addWidget(self.mode_controls, stretch=3)
        self.job_splitter.addWidget(sidebar)
        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(editor)
        self.material_target_label = QLabel()
        self.material_target_label.setWordWrap(True)
        self.material_target_label.setAlignment(Qt.AlignCenter)
        self.preview_stack.addWidget(self.material_target_label)
        self.job_splitter.addWidget(self.preview_stack)
        self.job_splitter.setStretchFactor(0, 0)
        self.job_splitter.setStretchFactor(1, 1)
        self.job_splitter.setSizes([300, 1180])
        layout.addWidget(self.job_splitter, stretch=1)
        editor.when_created(self._install_texture_editor)
        recolor.when_created(self._install_recolor_controls)
        self.set_texture_mode(self.job.mode, activate=False)

    def _with_texture_editor(self, callback) -> None:
        self.editor_container.when_created(callback)
        self.editor_container.request_widget()

    def _install_texture_editor(self, editor) -> None:
        if not hasattr(editor, "job"):
            return
        self._editor_controls = editor.left_scroll
        self.mode_controls.addWidget(self._editor_controls)
        editor.workspace_changed.connect(self._synchronize_texture_job)
        editor.workspace_mode_requested.connect(self._handle_editor_mode_request)
        editor._task_finished_on_ui.connect(self._queue_next_texture_source)
        self._synchronize_texture_job()
        self.set_texture_mode(self.job.mode)
        self._queue_next_texture_source()

    def _handle_editor_mode_request(self, mode: str) -> None:
        if mode == "review":
            self.show_texture_review(operation="replacement")
        else:
            self.set_texture_mode(mode)

    def _install_recolor_controls(self, recolor) -> None:
        self._recolor_controls = recolor
        self.set_texture_mode(self.job.mode)

    def set_texture_mode(self, mode: str, *, activate: bool = True) -> None:
        mode = normalize_texture_mode(mode)
        self._synchronize_texture_job()
        self.job.mode = mode
        editor = created_tool_widget(self.editor_container)
        if editor is not None and hasattr(editor, "set_workspace_mode"):
            editor.set_workspace_mode(mode)
        self.shell.settings.setValue(TEXTURE_MODE_SETTING, mode)
        for key, button in self.mode_buttons.items():
            button.setChecked(key == mode)
        if mode == "upscale":
            self.mode_controls.setCurrentWidget(self.upscale_controls)
            QTimer.singleShot(0, self, self._fit_upscale_sidebar)
        elif mode == "recolor":
            if activate:
                self.recolor_container.request_widget()
            self.mode_controls.setCurrentWidget(self.recolor_container)
        elif self._editor_controls is not None:
            self.mode_controls.setCurrentWidget(self._editor_controls)
        else:
            self.mode_controls.setCurrentIndex(0)
        self.preview_stack.setCurrentWidget(self.editor_container)
        if activate:
            self.editor_container.request_widget()

    def _fit_upscale_sidebar(self) -> None:
        if self.job.mode != "upscale" or not hasattr(self, "job_splitter"):
            return
        sizes = self.job_splitter.sizes()
        available = sum(sizes)
        if not available:
            return
        sidebar = self.job_splitter.widget(0)
        width = min(sidebar.maximumWidth(), max(
            sidebar.minimumWidth(), available - self.preview_stack.minimumSizeHint().width(),
        ))
        if sizes[0] != width:
            self.job_splitter.setSizes([width, available - width])

    def activate_texture_alias(self, key: str) -> None:
        mode = TEXTURE_TOOL_ALIASES.get(key, self.job.mode)
        if mode == "review":
            self.show_texture_review(operation="replacement")
        else:
            self.set_texture_mode(mode)

    def _choose_texture_sources(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add Textures", "", "Textures (*.dds *.png *.tga *.tif *.tiff *.bmp *.jpg *.jpeg)",
        )
        self.open_texture_sources([Path(path) for path in paths])

    def open_texture_sources(self, paths, *, binding=None) -> None:
        for path in paths:
            source = Path(path).expanduser().resolve()
            source_binding = binding or TextureEditorSourceBinding(source_path=str(source))
            self.job.add_source(source, source_binding)
            self._pending_texture_sources.append((source, source_binding))
        self._refresh_texture_assets()
        self._with_texture_editor(lambda _editor: self._queue_next_texture_source())

    def _queue_next_texture_source(self) -> None:
        QTimer.singleShot(0, self, self._open_next_texture_source)

    def _open_next_texture_source(self) -> None:
        editor = created_tool_widget(self.editor_container)
        if editor is None or not hasattr(editor, "job") or editor._busy() or not self._pending_texture_sources:
            return
        path, binding = self._pending_texture_sources.popleft()
        editor.open_source_path(path, binding=binding)
        if editor._task_thread is None:
            self._queue_next_texture_source()

    def _synchronize_texture_job(self) -> None:
        if self._syncing_texture_assets:
            return
        editor = created_tool_widget(self.editor_container)
        if editor is not None and hasattr(editor, "job"):
            self._syncing_texture_assets = True
            try:
                editor._store_active_session()
                self.job.synchronize_sessions(editor._active_session_index)
            finally:
                self._syncing_texture_assets = False
        self._refresh_texture_assets()

    def _refresh_texture_assets(self) -> None:
        self._syncing_texture_assets = True
        self.asset_list.blockSignals(True)
        try:
            self.asset_list.clear()
            for asset in self.job.assets.values():
                binding = asset.source_binding
                target = binding.archive_relative_path or binding.relative_path
                item = QTreeWidgetItem([asset.label, target or "Choose target"])
                item.setData(0, Qt.UserRole, asset.key)
                item.setCheckState(0, Qt.Checked if asset.key in self.job.selected else Qt.Unchecked)
                item.setToolTip(0, str(asset.source_path or target))
                self.asset_list.addTopLevelItem(item)
                if asset.key == self.job.active_asset_key:
                    self.asset_list.setCurrentItem(item)
        finally:
            self.asset_list.blockSignals(False)
            self._syncing_texture_assets = False
        self._filter_texture_assets()

    def _filter_texture_assets(self, *_args) -> None:
        needle = self.asset_search.text().strip().casefold()
        for index in range(self.asset_list.topLevelItemCount()):
            item = self.asset_list.topLevelItem(index)
            item.setHidden(bool(needle and needle not in (item.text(0) + " " + item.text(1)).casefold()))

    def _change_texture_selection(self, item, _column) -> None:
        if self._syncing_texture_assets:
            return
        key = item.data(0, Qt.UserRole)
        if item.checkState(0) == Qt.Checked:
            self.job.selected.add(key)
        else:
            self.job.selected.discard(key)

    def _remove_texture_asset(self) -> None:
        asset = self.job.assets.get(self.job.active_asset_key)
        editor = created_tool_widget(self.editor_container)
        if asset is None or self.job.busy or (editor is not None and editor._busy()):
            return
        if asset.session is not None and editor is not None:
            editor._close_document_tab(self.job.sessions.index(asset.session))
        self.job.assets.pop(asset.key)
        self.job.selected.discard(asset.key)
        if self.job.active_asset_key == asset.key:
            self.job.active_asset_key = ""
        self._pending_texture_sources = deque(
            (path, binding) for path, binding in self._pending_texture_sources
            if path != asset.source_path
        )
        if editor is not None:
            editor.set_workspace_mode(self.job.mode)
        self.preview_stack.setCurrentWidget(self.editor_container)
        self._synchronize_texture_job()

    def _select_texture_asset(self, item, _previous=None) -> None:
        if self._syncing_texture_assets or item is None:
            return
        asset = self.job.assets[item.data(0, Qt.UserRole)]
        editor = created_tool_widget(self.editor_container)
        if editor is not None and hasattr(editor, "set_workspace_mode"):
            editor.set_workspace_mode(self.job.mode)
        self.job.active_asset_key = asset.key
        target = asset.package_target
        if target is not None and target.target_kind == "material_color":
            self.material_target_label.setText(f"{target.game_path}\n{target.parameter_name}: {target.current_value}")
            self.preview_stack.setCurrentWidget(self.material_target_label)
        else:
            self.preview_stack.setCurrentWidget(self.editor_container)
            if asset.session is not None:
                def select(editor):
                    editor._store_active_session()
                    editor._load_session_index(self.job.sessions.index(asset.session))
                self._with_texture_editor(select)
            elif asset.source_path is not None:
                self.open_texture_sources([asset.source_path], binding=asset.binding)
            elif target is not None:
                self._with_texture_editor(lambda editor: self.open_texture_package_asset(asset, editor))
        recolor = created_tool_widget(self.recolor_container)
        if recolor is not None:
            recolor._handle_target_selection_changed()

    def _choose_texture_mod(self) -> None:
        self.set_texture_mode("recolor")
        self.recolor_container.when_created(lambda recolor: recolor._browse_source())

    def set_recolor_analysis(self, analysis) -> None:
        self.job.recolor_analysis = analysis
        if analysis is None:
            return
        for target in analysis.targets:
            identity = f"{analysis.package_path}:{target.game_path}"
            asset = next((item for item in self.job.assets.values()
                          if item.binding.source_identity_path == identity), None)
            if asset is None:
                binding = TextureEditorSourceBinding(
                    launch_origin="recolor_variants", display_name=target.label,
                    source_identity_path=identity, relative_path=target.game_path,
                    archive_relative_path=target.game_path, original_dds_format=target.dds_format,
                    texture_type=target.texture_type, semantic_subtype=target.semantic_subtype,
                )
                asset = TextureJobAsset(None, binding, package_target=target)
                self.job.assets[asset.key] = asset
                if target.editable:
                    self.job.selected.add(asset.key)
            else:
                asset.package_target = target
            asset.package_path = Path(analysis.package_path)
        self._refresh_texture_assets()

    def show_texture_result_preview(self, source_image, result_image) -> None:
        if self.job.mode != "recolor":
            return
        self.preview_stack.setCurrentWidget(self.editor_container)
        self._with_texture_editor(lambda editor: editor.show_workspace_preview(source_image, result_image))

    def show_texture_review(self, _checked=False, *, operation: str | None = None) -> None:
        self._synchronize_texture_job()
        if self._review_dialog is None:
            self._build_texture_review()
        key = operation or self.job.mode
        index = self.export_operation.findData(key)
        if index >= 0:
            self.export_operation.setCurrentIndex(index)
        self._review_dialog.show()
        self._review_dialog.raise_()
        self._review_dialog.activateWindow()

    def _build_texture_review(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Review & Export")
        dialog.resize(1050, 730)
        layout = QVBoxLayout(dialog)
        self.export_operation = QComboBox()
        for label, key in (("Edited texture", "edit"), ("Replacement matches", "replacement"),
                           ("Recolor package", "recolor"), ("Upscale package", "upscale")):
            self.export_operation.addItem(label, key)
        layout.addWidget(self.export_operation)
        self.export_pages = QStackedWidget()
        self.editor_export_page = QWidget()
        edit_layout = QVBoxLayout(self.editor_export_page)
        def add_editor_export_controls(editor):
            if hasattr(editor, "native_export_controls"):
                edit_layout.insertWidget(0, editor.native_export_controls)
                editor.native_export_controls.show()
        self.editor_container.when_created(add_editor_export_controls)
        for label, method in (("Export PNG", "save_flattened_png_dialog"),
                              ("Save Project", "save_project_dialog")):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, name=method: self._with_texture_editor(lambda editor: getattr(editor, name)()))
            edit_layout.addWidget(button)
        edit_layout.addStretch(1)
        self.export_pages.addWidget(self.editor_export_page)
        self.export_pages.addWidget(self.matcher_container)
        self.recolor_export_page = QWidget()
        self.recolor_export_layout = QVBoxLayout(self.recolor_export_page)
        self.export_pages.addWidget(self.recolor_export_page)
        def add_recolor_export_controls(recolor):
            self.recolor_export_layout.addWidget(recolor.export_controls)
            recolor.export_controls.show()
        self.recolor_container.when_created(add_recolor_export_controls)
        self.export_pages.addWidget(self.upscale_export_controls)
        layout.addWidget(self.export_pages, stretch=1)
        self.export_operation.currentIndexChanged.connect(self._select_texture_export)
        self._review_dialog = dialog
        self._select_texture_export(0)

    def _select_texture_export(self, index: int) -> None:
        self.export_pages.setCurrentIndex(index)
        key = self.export_operation.itemData(index)
        if key == "replacement":
            self.matcher_container.when_created(lambda _matcher: self.prepare_replacement_review())
            self.editor_container.when_created(lambda _editor: self.prepare_replacement_review())
            self.editor_container.request_widget()
            self.matcher_container.request_widget()
        elif key == "recolor":
            self.recolor_container.request_widget()
