"""Recolor controls for the shared Textures workspace."""

from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget


class SharedRecolorModeMixin:
    def _capture_shared_recolor_preview(self):
        if self.workspace is None:
            return None, None
        self.workspace._synchronize_texture_job()
        job = self.workspace.job
        asset = job.assets.get(job.active_asset_key)
        if asset is None:
            return None, None
        operation = job.begin("recolor_preview", asset_keys=(asset.key,))
        if asset.session is None:
            return operation, None
        from copy import deepcopy
        from cdmw.ui.texture_workflow.editor_export_tasks import copy_texture_editor_layer_pixels
        return operation, (deepcopy(asset.session.document), copy_texture_editor_layer_pixels(asset.session.layer_pixels))

    def _build_shared_recolor_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        body = QWidget()
        controls = QVBoxLayout(body)
        controls.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(body)
        layout.addWidget(scroll)
        self.summary_label = QLabel("Add a mod to recolor its textures and material colors.")
        self.summary_label.setWordWrap(True)
        controls.addWidget(self.summary_label)
        self._build_source_section(controls)
        self._build_template_section(controls)
        self.preview_summary_label = QLabel()
        self.preview_summary_label.setWordWrap(True)
        controls.addWidget(self.preview_summary_label)
        self.selected_target_label = QLabel()
        self.selected_target_label.setWordWrap(True)
        controls.addWidget(self.selected_target_label)
        self.refresh_selected_preview_button = QPushButton("Preview Recolor")
        self.refresh_selected_preview_button.clicked.connect(self.refresh_selected_preview)
        controls.addWidget(self.refresh_selected_preview_button)
        self.open_selected_in_editor_button = QPushButton("Edit Selected Texture")
        self.open_selected_in_editor_button.clicked.connect(self.open_selected_target_in_editor)
        controls.addWidget(self.open_selected_in_editor_button)
        self.material_preview_widget = QWidget()
        self.material_preview_widget.hide()
        swatches = QVBoxLayout(self.material_preview_widget)
        self.material_current_swatch = QLabel("Current")
        self.material_target_swatch = QLabel("Target")
        swatches.addWidget(self.material_current_swatch)
        swatches.addWidget(self.material_target_swatch)
        controls.addWidget(self.material_preview_widget)
        controls.addStretch(1)
        self.export_controls = QWidget(self)
        self.export_controls.hide()
        export_layout = QVBoxLayout(self.export_controls)
        self._build_output_section(export_layout)
        self._build_results_section(export_layout)

    def _sync_shared_recolor_target(self) -> None:
        if self._worker_kind == "preview":
            self._operation_request_id += 1
            if self.build_worker is not None:
                self.build_worker.stop()
        self.current_preview_image = None
        target = self._selected_target()
        material = target is not None and target.target_kind == "material_color"
        self.material_preview_widget.setVisible(material)
        self.selected_target_label.setText(target.game_path if target else "Select a mod target in the asset list.")
        if material:
            rule = self._matching_rule_for_target(target)
            self._set_color_swatch(self.material_current_swatch, target.current_value, "Current")
            self._set_color_swatch(self.material_target_swatch, rule.target_color if rule else "#C85A30", "Target")
        self._sync_action_state()
