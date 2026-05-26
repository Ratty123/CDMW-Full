from __future__ import annotations

import dataclasses
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from PySide6.QtCore import QObject, QSettings, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.core.recolor_variants import (
    RecolorVariantAnalysis,
    RecolorVariantBuildResult,
    RecolorVariantOutputProfile,
    RecolorVariantRule,
    RecolorVariantTemplate,
    analyze_recolor_variant_package,
    build_recolor_variant_outputs,
    export_recolor_variant_templates,
    import_recolor_variant_templates,
    load_recolor_variant_templates,
    preview_recolor_variant_template,
    recolor_export_options_for_manager,
    save_recolor_variant_templates,
)
from cdmw.models import RunCancelled
from cdmw.ui.widgets import (
    EmptyStatePanel,
    FlatSectionPanel,
    build_responsive_splitter_sizes,
    make_tree_columns_persistent,
    responsive_sidebar_bounds,
    set_sidebar_width_policy,
)


class RecolorVariantBuildWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)
    log_message = Signal(str)
    progress_changed = Signal(int, int, str)
    finished = Signal()

    def __init__(
        self,
        analysis: RecolorVariantAnalysis,
        template: RecolorVariantTemplate,
        output_root: Path,
        profiles: Sequence[RecolorVariantOutputProfile],
        *,
        texconv_path: Optional[Path],
        overwrite_existing: bool,
    ) -> None:
        super().__init__()
        self.analysis = analysis
        self.template = template
        self.output_root = output_root
        self.profiles = tuple(profiles)
        self.texconv_path = texconv_path
        self.overwrite_existing = bool(overwrite_existing)
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            result = build_recolor_variant_outputs(
                self.analysis,
                self.template,
                self.output_root,
                self.profiles,
                texconv_path=self.texconv_path,
                overwrite_existing=self.overwrite_existing,
                stop_event=self.stop_event,
                on_log=self.log_message.emit,
                on_progress=self.progress_changed.emit,
            )
            self.completed.emit(result)
        except RunCancelled:
            self.failed.emit("Recolor variant build cancelled.")
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()


class RecolorVariantsTab(QWidget):
    status_message_requested = Signal(str, bool)

    def __init__(
        self,
        *,
        settings: QSettings,
        base_dir: Path,
        get_texconv_path: Callable[[], str],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("RecolorVariantsTab")
        self.settings = settings
        self.base_dir = Path(base_dir).expanduser().resolve()
        self.get_texconv_path = get_texconv_path
        self.analysis: Optional[RecolorVariantAnalysis] = None
        self.templates: List[RecolorVariantTemplate] = list(load_recolor_variant_templates(self.base_dir))
        self.last_output_roots: tuple[Path, ...] = ()
        self.worker_thread: Optional[QThread] = None
        self.build_worker: Optional[RecolorVariantBuildWorker] = None

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(8)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        root_layout.addWidget(self.splitter, stretch=1)

        controls_widget = QWidget()
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(8)
        set_sidebar_width_policy(controls_widget, role="workflow")
        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setFrameShape(QScrollArea.NoFrame)
        controls_scroll.setWidget(controls_widget)
        self.splitter.addWidget(controls_scroll)

        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)
        self.splitter.addWidget(main_widget)
        content_min, _content_pref, _content_max = responsive_sidebar_bounds(self, role="wide")
        main_widget.setMinimumWidth(content_min)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes(build_responsive_splitter_sizes(1280, [35, 65], [360, 520]))

        self._build_source_section(controls_layout)
        self._build_template_section(controls_layout)
        self._build_output_section(controls_layout)
        controls_layout.addStretch(1)

        self.summary_label = QLabel("Choose a loose or zip mod, then analyze it for safe recolor targets.")
        self.summary_label.setObjectName("HintLabel")
        self.summary_label.setWordWrap(True)
        main_layout.addWidget(self.summary_label)

        self.preview_summary_label = QLabel("Preview a template to see the exact texture and material-color impact before building.")
        self.preview_summary_label.setObjectName("RecolorVariantPreviewSummary")
        self.preview_summary_label.setWordWrap(True)
        main_layout.addWidget(self.preview_summary_label)

        self.targets_tree = QTreeWidget()
        self.targets_tree.setObjectName("RecolorVariantTargetsTree")
        self.targets_tree.setHeaderLabels(["Target", "Kind", "Slot / Parameter", "Semantic", "State", "DDS"])
        self.targets_tree.setAlternatingRowColors(True)
        self.targets_tree.setRootIsDecorated(False)
        self.targets_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.targets_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.targets_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.targets_tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.targets_tree.header().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.targets_tree.header().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        make_tree_columns_persistent(self.targets_tree, self.settings, "recolor_variants/targets_tree")
        main_layout.addWidget(self.targets_tree, stretch=3)

        self.empty_state = EmptyStatePanel(
            "No analysis loaded",
            "Analyze a source mod to show safe basecolor/overlay texture slots and locked technical maps.",
            compact=True,
        )
        self.empty_state.setVisible(True)
        main_layout.addWidget(self.empty_state)

        outputs_group = FlatSectionPanel("Build Outputs", body_margins=(8, 8, 8, 8), body_spacing=6)
        self.outputs_tree = QTreeWidget()
        self.outputs_tree.setObjectName("RecolorVariantOutputsTree")
        self.outputs_tree.setHeaderLabels(["Output folder", "Result", "Changed"])
        self.outputs_tree.setAlternatingRowColors(True)
        self.outputs_tree.setRootIsDecorated(False)
        self.outputs_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.outputs_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.outputs_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        make_tree_columns_persistent(self.outputs_tree, self.settings, "recolor_variants/outputs_tree")
        outputs_group.body_layout.addWidget(self.outputs_tree)
        main_layout.addWidget(outputs_group, stretch=1)

        log_group = FlatSectionPanel("Build Log", body_margins=(8, 8, 8, 8), body_spacing=6)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setObjectName("RecolorVariantBuildLog")
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(2000)
        log_group.body_layout.addWidget(self.log_edit)
        main_layout.addWidget(log_group, stretch=1)

        self._reload_template_combo()
        self._load_settings()
        self._sync_template_editor()
        self._sync_action_state()

    def _build_source_section(self, parent_layout: QVBoxLayout) -> None:
        section = FlatSectionPanel("Source Mod", body_margins=(10, 10, 10, 10), body_spacing=8)
        layout = QGridLayout()
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)
        layout.setColumnStretch(1, 1)
        self.source_path_edit = QLineEdit()
        self.source_path_edit.setPlaceholderText("Folder or .zip package")
        self.source_browse_button = QPushButton("Browse")
        self.analyze_button = QPushButton("Analyze Mod")
        layout.addWidget(QLabel("Source"), 0, 0)
        source_row = QHBoxLayout()
        source_row.setContentsMargins(0, 0, 0, 0)
        source_row.setSpacing(6)
        source_row.addWidget(self.source_path_edit, stretch=1)
        source_row.addWidget(self.source_browse_button)
        layout.addLayout(source_row, 0, 1)
        layout.addWidget(self.analyze_button, 1, 1)
        section.body_layout.addLayout(layout)
        parent_layout.addWidget(section)
        self.source_browse_button.clicked.connect(self._browse_source)
        self.analyze_button.clicked.connect(self.analyze_source)

    def _build_template_section(self, parent_layout: QVBoxLayout) -> None:
        section = FlatSectionPanel("Global Template", body_margins=(10, 10, 10, 10), body_spacing=8)
        layout = QGridLayout()
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)
        layout.setColumnStretch(1, 1)
        self.template_combo = QComboBox()
        self.template_name_edit = QLineEdit()
        self.target_kind_combo = QComboBox()
        self.target_kind_combo.addItem("Texture slots", "texture_slot")
        self.target_kind_combo.addItem("Material colors", "material_color")
        self.slot_kind_combo = QComboBox()
        self.slot_kind_combo.addItem("Base / overlay", "base")
        self.slot_kind_combo.addItem("Emissive", "emissive")
        self.filename_glob_edit = QLineEdit("*.dds")
        self.parameter_glob_edit = QLineEdit("*")
        self.operation_combo = QComboBox()
        self.operation_combo.addItem("Tint whole texture", "tint")
        self.operation_combo.addItem("Replace selected color", "replace_color")
        self.operation_combo.addItem("Set material color", "set_color")
        self.source_color_edit = QLineEdit("#808080")
        self.target_color_edit = QLineEdit("#C85A30")
        self.tolerance_spin = QSpinBox()
        self.tolerance_spin.setRange(0, 255)
        self.tolerance_spin.setValue(48)
        self.strength_spin = QSpinBox()
        self.strength_spin.setRange(1, 100)
        self.strength_spin.setValue(100)
        self.preserve_luma_checkbox = QCheckBox("Preserve shading / luminance")
        self.preserve_luma_checkbox.setChecked(True)
        self.import_template_button = QPushButton("Import JSON")
        self.export_template_button = QPushButton("Export JSON")
        self.save_template_button = QPushButton("Save Template")
        self.preview_template_button = QPushButton("Preview Matches")

        rows = (
            ("Template", self.template_combo),
            ("Name", self.template_name_edit),
            ("Target kind", self.target_kind_combo),
            ("Slot kind", self.slot_kind_combo),
            ("Texture glob", self.filename_glob_edit),
            ("Material parameter", self.parameter_glob_edit),
            ("Operation", self.operation_combo),
            ("Source color", self.source_color_edit),
            ("Target color", self.target_color_edit),
            ("Tolerance", self.tolerance_spin),
            ("Strength", self.strength_spin),
        )
        for row, (label, widget) in enumerate(rows):
            layout.addWidget(QLabel(label), row, 0)
            layout.addWidget(widget, row, 1)
        layout.addWidget(self.preserve_luma_checkbox, len(rows), 1)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        actions.addWidget(self.import_template_button)
        actions.addWidget(self.export_template_button)
        actions.addWidget(self.save_template_button)
        actions.addWidget(self.preview_template_button)
        layout.addLayout(actions, len(rows) + 1, 1)
        section.body_layout.addLayout(layout)
        parent_layout.addWidget(section)

        self.template_combo.currentIndexChanged.connect(self._sync_template_editor)
        self.target_kind_combo.currentIndexChanged.connect(self._sync_template_kind_controls)
        self.import_template_button.clicked.connect(self.import_templates)
        self.export_template_button.clicked.connect(self.export_templates)
        self.save_template_button.clicked.connect(self.save_current_template)
        self.preview_template_button.clicked.connect(self.preview_current_template)

    def _build_output_section(self, parent_layout: QVBoxLayout) -> None:
        section = FlatSectionPanel("Output", body_margins=(10, 10, 10, 10), body_spacing=8)
        layout = QGridLayout()
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)
        layout.setColumnStretch(1, 1)
        self.output_root_edit = QLineEdit(str((self.base_dir / "recolor_variant_export").resolve()))
        self.output_browse_button = QPushButton("Browse")
        self.overwrite_checkbox = QCheckBox("Clear existing generated package folders")
        self.overwrite_checkbox.setObjectName("RecolorVariantNoInPlaceOverwrite")
        self.overwrite_checkbox.setToolTip("This only clears generated output folders. The source mod is never modified in place.")
        self.build_button = QPushButton("Build Variants")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.open_output_button = QPushButton("Open Output Folder")
        self.profile_checkboxes: Dict[str, QCheckBox] = {}
        profiles_group = QGroupBox("Manager outputs")
        profiles_layout = QVBoxLayout(profiles_group)
        for profile_id, label, checked in (
            ("universal", "Universal / game-relative", True),
            ("cdumm", "CDUMM files/ wrapper", False),
            ("jmm", "JMM JSON", False),
            ("dmm", "Definitive Mod Manager", False),
            ("crimson_sharp", "Crimson Sharp / Browser", False),
            ("field_json", "Field-JSON v3.1", False),
        ):
            checkbox = QCheckBox(label)
            checkbox.setChecked(checked)
            self.profile_checkboxes[profile_id] = checkbox
            profiles_layout.addWidget(checkbox)
        layout.addWidget(QLabel("Parent root"), 0, 0)
        output_row = QHBoxLayout()
        output_row.setContentsMargins(0, 0, 0, 0)
        output_row.setSpacing(6)
        output_row.addWidget(self.output_root_edit, stretch=1)
        output_row.addWidget(self.output_browse_button)
        layout.addLayout(output_row, 0, 1)
        layout.addWidget(profiles_group, 1, 0, 1, 2)
        layout.addWidget(self.overwrite_checkbox, 2, 0, 1, 2)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        actions.addWidget(self.build_button)
        actions.addWidget(self.stop_button)
        layout.addLayout(actions, 3, 1)
        layout.addWidget(self.open_output_button, 4, 1)
        section.body_layout.addLayout(layout)
        parent_layout.addWidget(section)

        self.output_browse_button.clicked.connect(self._browse_output_root)
        self.build_button.clicked.connect(self.start_build)
        self.stop_button.clicked.connect(self.stop_build)
        self.open_output_button.clicked.connect(self.open_output_folder)

    def _load_settings(self) -> None:
        self.source_path_edit.setText(str(self.settings.value("recolor_variants/source_path", "")))
        self.output_root_edit.setText(str(self.settings.value("recolor_variants/output_root", self.output_root_edit.text())))
        for profile_id, checkbox in self.profile_checkboxes.items():
            value = self.settings.value(f"recolor_variants/profile_{profile_id}", checkbox.isChecked())
            checkbox.setChecked(_settings_bool(value, checkbox.isChecked()))
        self.overwrite_checkbox.setChecked(_settings_bool(self.settings.value("recolor_variants/overwrite_output", False), False))

    def _save_settings(self) -> None:
        self.settings.setValue("recolor_variants/source_path", self.source_path_edit.text())
        self.settings.setValue("recolor_variants/output_root", self.output_root_edit.text())
        self.settings.setValue("recolor_variants/overwrite_output", self.overwrite_checkbox.isChecked())
        for profile_id, checkbox in self.profile_checkboxes.items():
            self.settings.setValue(f"recolor_variants/profile_{profile_id}", checkbox.isChecked())

    def _browse_source(self) -> None:
        start = self.source_path_edit.text().strip() or str(self.base_dir)
        directory = QFileDialog.getExistingDirectory(self, "Select loose mod folder", start)
        if directory:
            self.source_path_edit.setText(directory)
            return
        file_path, _filter = QFileDialog.getOpenFileName(self, "Select mod zip", start, "Mod packages (*.zip);;All files (*.*)")
        if file_path:
            self.source_path_edit.setText(file_path)

    def _browse_output_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select recolor variant output root", self.output_root_edit.text().strip() or str(self.base_dir))
        if selected:
            self.output_root_edit.setText(selected)

    def _reload_template_combo(self) -> None:
        current_id = self.current_template().template_id if self.template_combo.count() else ""
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        for template in self.templates:
            self.template_combo.addItem(template.name or "Recolor Template", template.template_id)
        index = self.template_combo.findData(current_id)
        if index >= 0:
            self.template_combo.setCurrentIndex(index)
        self.template_combo.blockSignals(False)

    def current_template(self) -> RecolorVariantTemplate:
        template_id = str(self.template_combo.currentData() or "")
        for template in self.templates:
            if template.template_id == template_id:
                return template
        if self.templates:
            return self.templates[0]
        return RecolorVariantTemplate(name="Recolor Template")

    def _sync_template_editor(self) -> None:
        template = self.current_template()
        rule = template.rules[0] if template.rules else RecolorVariantRule()
        self.template_name_edit.setText(template.name or "Recolor Template")
        self._set_combo_value(self.target_kind_combo, rule.target_kind)
        self._set_combo_value(self.slot_kind_combo, rule.slot_kind or "base")
        self.filename_glob_edit.setText(rule.filename_glob or "*.dds")
        self.parameter_glob_edit.setText(rule.parameter_name or "*")
        self._set_combo_value(self.operation_combo, rule.operation)
        self.source_color_edit.setText(rule.source_color)
        self.target_color_edit.setText(rule.target_color)
        self.tolerance_spin.setValue(rule.tolerance)
        self.strength_spin.setValue(rule.strength)
        self.preserve_luma_checkbox.setChecked(rule.preserve_luminance)
        self._sync_template_kind_controls()

    def _sync_template_kind_controls(self) -> None:
        texture_mode = str(self.target_kind_combo.currentData() or "texture_slot") == "texture_slot"
        self.slot_kind_combo.setEnabled(texture_mode)
        self.filename_glob_edit.setEnabled(texture_mode)
        self.parameter_glob_edit.setEnabled(not texture_mode)
        self.tolerance_spin.setEnabled(texture_mode)
        self.preserve_luma_checkbox.setEnabled(texture_mode)

    def _set_combo_value(self, combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _template_from_controls(self) -> RecolorVariantTemplate:
        base = self.current_template()
        target_kind = str(self.target_kind_combo.currentData() or "texture_slot")
        operation = str(self.operation_combo.currentData() or "tint")
        if target_kind == "material_color":
            operation = "set_color"
        rule = RecolorVariantRule(
            rule_id=(base.rules[0].rule_id if base.rules else "rule"),
            label="Template rule",
            target_kind=target_kind,
            slot_kind=str(self.slot_kind_combo.currentData() or "base"),
            filename_glob=self.filename_glob_edit.text().strip() or "*.dds",
            parameter_name=self.parameter_glob_edit.text().strip() or "*",
            operation=operation,
            source_color=self.source_color_edit.text().strip() or "#808080",
            target_color=self.target_color_edit.text().strip() or "#C85A30",
            tolerance=self.tolerance_spin.value(),
            strength=self.strength_spin.value(),
            preserve_luminance=self.preserve_luma_checkbox.isChecked(),
        )
        return dataclasses.replace(
            base,
            name=self.template_name_edit.text().strip() or "Recolor Template",
            rules=(rule,),
        )

    def _replace_or_append_template(self, template: RecolorVariantTemplate) -> None:
        replaced = False
        updated: list[RecolorVariantTemplate] = []
        for item in self.templates:
            if item.template_id == template.template_id:
                updated.append(template)
                replaced = True
            else:
                updated.append(item)
        if not replaced:
            updated.append(template)
        self.templates = updated

    def save_current_template(self) -> None:
        template = self._template_from_controls()
        self._replace_or_append_template(template)
        path = save_recolor_variant_templates(self.base_dir, self.templates)
        self._reload_template_combo()
        self._set_combo_value(self.template_combo, template.template_id)
        self._append_log(f"Saved global recolor template: {path}")
        self.status_message_requested.emit("Recolor template saved.", False)

    def import_templates(self) -> None:
        file_path, _filter = QFileDialog.getOpenFileName(
            self,
            "Import recolor templates",
            str(self.base_dir),
            "Recolor templates (*.json);;All files (*.*)",
        )
        if not file_path:
            return
        try:
            self.templates = list(import_recolor_variant_templates(self.base_dir, Path(file_path), merge=True))
            self._reload_template_combo()
            self._sync_template_editor()
            self._append_log(f"Imported global recolor templates: {file_path}")
            self.status_message_requested.emit("Recolor templates imported.", False)
        except Exception as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            self.status_message_requested.emit(f"Recolor template import failed: {exc}", True)

    def export_templates(self) -> None:
        file_path, _filter = QFileDialog.getSaveFileName(
            self,
            "Export recolor templates",
            str(self.base_dir / "recolor_variant_templates.json"),
            "Recolor templates (*.json);;All files (*.*)",
        )
        if not file_path:
            return
        try:
            template = self._template_from_controls()
            self._replace_or_append_template(template)
            save_recolor_variant_templates(self.base_dir, self.templates)
            path = export_recolor_variant_templates(self.base_dir, Path(file_path))
            self._append_log(f"Exported global recolor templates: {path}")
            self.status_message_requested.emit("Recolor templates exported.", False)
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            self.status_message_requested.emit(f"Recolor template export failed: {exc}", True)

    def analyze_source(self) -> None:
        source_text = self.source_path_edit.text().strip()
        if not source_text:
            self.status_message_requested.emit("Choose a source mod folder or zip first.", True)
            return
        source = Path(source_text).expanduser()
        if not source.exists():
            self.status_message_requested.emit(f"Source mod not found: {source}", True)
            return
        self._save_settings()
        self._append_log(f"Analyzing recolor targets: {source}")
        try:
            self.analysis = analyze_recolor_variant_package(source)
        except Exception as exc:
            self.analysis = None
            self.status_message_requested.emit(f"Recolor analysis failed: {exc}", True)
            return
        self._populate_targets_tree()
        editable_count = len(self.analysis.editable_targets)
        self.summary_label.setText(
            f"{self.analysis.package_info.title}: {editable_count} editable target(s), "
            f"{len(self.analysis.targets) - editable_count} locked/risky target(s), "
            f"{len(self.analysis.payload_paths)} payload file(s)."
        )
        self.outputs_tree.clear()
        self._refresh_preview_summary()
        for warning in self.analysis.warnings:
            self._append_log(f"Warning: {warning}")
        self.status_message_requested.emit("Recolor analysis complete.", False)
        self._sync_action_state()

    def _populate_targets_tree(self) -> None:
        self.targets_tree.clear()
        if self.analysis is None:
            self.empty_state.setVisible(True)
            return
        for target in self.analysis.targets:
            state = "Editable" if target.editable else f"Locked: {target.locked_reason}"
            dds_text = ""
            if target.width and target.height:
                dds_text = f"{target.width}x{target.height} {target.texconv_format} mips {target.mip_count}"
            item = QTreeWidgetItem(
                [
                    target.game_path,
                    target.target_kind,
                    target.slot_kind or target.parameter_name,
                    f"{target.texture_type}/{target.semantic_subtype}" if target.target_kind == "texture_slot" else target.current_value,
                    state,
                    dds_text,
                ]
            )
            if not target.editable:
                item.setForeground(4, Qt.GlobalColor.darkYellow)
            self.targets_tree.addTopLevelItem(item)
        self.empty_state.setVisible(self.targets_tree.topLevelItemCount() == 0)

    def _refresh_preview_summary(self) -> None:
        if self.analysis is None:
            self.preview_summary_label.setText("Preview a template to see the exact texture and material-color impact before building.")
            return
        preview = preview_recolor_variant_template(self.analysis, self._template_from_controls())
        if preview.matched_target_ids:
            self.preview_summary_label.setText(
                f"Preview impact: {len(preview.matched_texture_paths)} DDS texture(s), "
                f"{len(preview.matched_material_paths)} material color value(s), "
                f"{len(preview.skipped_targets)} locked/risky match(es) skipped."
            )
        else:
            self.preview_summary_label.setText("Preview impact: no safe editable targets match this template.")

    def preview_current_template(self) -> None:
        if self.analysis is None:
            self.status_message_requested.emit("Analyze a source mod first.", True)
            return
        template = self._template_from_controls()
        preview = preview_recolor_variant_template(self.analysis, template)
        self._refresh_preview_summary()
        self._append_log(
            f"Template preview: {len(preview.matched_texture_paths)} texture(s), "
            f"{len(preview.matched_material_paths)} material value(s)."
        )
        for warning in preview.warnings:
            self._append_log(f"Warning: {warning}")
        for skipped in preview.skipped_targets[:12]:
            self._append_log(f"Skipped locked target: {skipped}")
        self.status_message_requested.emit("Recolor template preview updated.", False)

    def _selected_profiles(self) -> tuple[RecolorVariantOutputProfile, ...]:
        profiles: list[RecolorVariantOutputProfile] = []
        labels = {
            "universal": "Universal",
            "cdumm": "CDUMM",
            "jmm": "JMM JSON",
            "dmm": "Definitive Mod Manager",
            "crimson_sharp": "Crimson Sharp",
            "field_json": "Field-JSON v3.1",
        }
        suffixes = {
            "universal": "",
            "cdumm": "CDUMM",
            "jmm": "JMM",
            "dmm": "DMM",
            "crimson_sharp": "CrimsonSharp",
            "field_json": "FieldJSON",
        }
        for profile_id, checkbox in self.profile_checkboxes.items():
            if not checkbox.isChecked():
                continue
            export_options = recolor_export_options_for_manager(profile_id)
            profiles.append(
                RecolorVariantOutputProfile(
                    profile_id=profile_id,
                    label=labels.get(profile_id, profile_id),
                    enabled=True,
                    package_title_suffix=suffixes.get(profile_id, profile_id),
                    export_options=export_options,
                )
            )
        return tuple(profiles)

    def start_build(self) -> None:
        if self.analysis is None:
            self.status_message_requested.emit("Analyze a source mod first.", True)
            return
        profiles = self._selected_profiles()
        if not profiles:
            self.status_message_requested.emit("Select at least one manager output.", True)
            return
        output_root_text = self.output_root_edit.text().strip()
        if not output_root_text:
            self.status_message_requested.emit("Choose an output root first.", True)
            return
        self._save_settings()
        template = self._template_from_controls()
        texconv_text = self.get_texconv_path().strip()
        texconv_path = Path(texconv_text).expanduser() if texconv_text else None
        if texconv_path is not None and not texconv_path.is_file():
            texconv_path = None
        self.build_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.outputs_tree.clear()
        self._refresh_preview_summary()
        self._append_log("Starting recolor variant build. Source mod will not be modified in place.")
        self.worker_thread = QThread(self)
        self.build_worker = RecolorVariantBuildWorker(
            self.analysis,
            template,
            Path(output_root_text),
            profiles,
            texconv_path=texconv_path,
            overwrite_existing=self.overwrite_checkbox.isChecked(),
        )
        self.build_worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.build_worker.run)
        self.build_worker.completed.connect(self._handle_build_complete)
        self.build_worker.failed.connect(self._handle_build_failed)
        self.build_worker.log_message.connect(self._append_log)
        self.build_worker.progress_changed.connect(self._handle_progress)
        self.build_worker.finished.connect(self.worker_thread.quit)
        self.build_worker.finished.connect(self.build_worker.deleteLater)
        self.worker_thread.finished.connect(self._handle_worker_finished)
        self.worker_thread.start()

    def stop_build(self) -> None:
        if self.build_worker is not None:
            self.build_worker.stop()
            self._append_log("Stopping recolor variant build...")

    @Slot(object)
    def _handle_build_complete(self, result: RecolorVariantBuildResult) -> None:
        self.last_output_roots = result.output_roots
        self._populate_outputs_tree(result)
        for warning in result.warnings:
            self._append_log(f"Warning: {warning}")
        for error in result.errors:
            self._append_log(f"Error: {error}")
        if result.succeeded:
            self._append_log(
                f"Built {len(result.output_roots)} recolor output(s), "
                f"changed {len(result.changed_texture_paths)} texture(s) and "
                f"{len(result.changed_material_paths)} material value(s)."
            )
            self.status_message_requested.emit("Recolor variants built.", False)
        else:
            self.status_message_requested.emit("Recolor variant build did not produce outputs.", True)

    @Slot(str)
    def _handle_build_failed(self, message: str) -> None:
        self.outputs_tree.clear()
        self.outputs_tree.addTopLevelItem(QTreeWidgetItem(["Build", "Failed", message]))
        self._append_log(f"Build failed: {message}")
        self.status_message_requested.emit(f"Recolor variant build failed: {message}", True)

    def _populate_outputs_tree(self, result: RecolorVariantBuildResult) -> None:
        self.outputs_tree.clear()
        changed_text = f"{len(result.changed_texture_paths)} texture(s), {len(result.changed_material_paths)} material value(s)"
        for output_root in result.output_roots:
            self.outputs_tree.addTopLevelItem(QTreeWidgetItem([str(output_root), "Built", changed_text]))
        for error in result.errors:
            self.outputs_tree.addTopLevelItem(QTreeWidgetItem(["Build", "Error", error]))
        if self.outputs_tree.topLevelItemCount() == 0:
            self.outputs_tree.addTopLevelItem(QTreeWidgetItem(["Build", "No outputs", "No manager output folder was produced."]))

    @Slot(int, int, str)
    def _handle_progress(self, current: int, total: int, label: str) -> None:
        self.status_message_requested.emit(f"Recolor variants: {label}", False)

    @Slot()
    def _handle_worker_finished(self) -> None:
        if self.worker_thread is not None:
            self.worker_thread.deleteLater()
        self.worker_thread = None
        self.build_worker = None
        self.build_button.setEnabled(self.analysis is not None)
        self.stop_button.setEnabled(False)

    def open_output_folder(self) -> None:
        if self.last_output_roots:
            target = self.last_output_roots[0]
        else:
            target = Path(self.output_root_edit.text().strip() or self.base_dir)
        target.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _append_log(self, message: str) -> None:
        self.log_edit.appendPlainText(str(message))

    def _sync_action_state(self) -> None:
        busy = self.worker_thread is not None
        self.build_button.setEnabled(self.analysis is not None and not busy)
        self.preview_template_button.setEnabled(self.analysis is not None and not busy)
        self.stop_button.setEnabled(busy)


def _settings_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    return bool(default)
