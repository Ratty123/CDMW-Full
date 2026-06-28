from __future__ import annotations

import dataclasses
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from PySide6.QtCore import QObject, QSettings, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
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
    RecolorVariantPreviewImage,
    RecolorVariantRule,
    RecolorVariantTemplate,
    analyze_recolor_variant_package,
    build_recolor_variant_outputs,
    export_recolor_variant_templates,
    import_recolor_variant_templates,
    load_recolor_variant_templates,
    matching_recolor_variant_rule,
    preview_recolor_variant_target_image,
    preview_recolor_variant_template,
    recolor_export_options_for_manager,
    save_recolor_variant_templates,
    texture_editor_settings_for_recolor_variant_rule,
)
from cdmw.models import RunCancelled, TextureEditorSourceBinding, TextureEditorToolSettings
from cdmw.ui.widgets import (
    CollapsibleSection,
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


class _RecolorPreviewLabel(QLabel):
    def __init__(self, placeholder: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(placeholder, parent)
        self._placeholder = placeholder
        self._source_pixmap = QPixmap()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("QLabel { border: 1px solid palette(mid); background: palette(base); }")

    def set_placeholder(self, text: str = "") -> None:
        self._placeholder = text or self._placeholder
        self._source_pixmap = QPixmap()
        self.clear()
        self.setText(self._placeholder)

    def set_preview_path(self, path: Path, fallback: str) -> None:
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.set_placeholder(fallback)
            return
        self._placeholder = fallback
        self._source_pixmap = pixmap
        self.setText("")
        self._sync_pixmap()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._sync_pixmap()

    def _sync_pixmap(self) -> None:
        if self._source_pixmap.isNull():
            return
        target_size = self.contentsRect().size()
        if target_size.width() <= 1 or target_size.height() <= 1:
            return
        self.setPixmap(self._source_pixmap.scaled(target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))


class RecolorVariantsTab(QWidget):
    status_message_requested = Signal(str, bool)
    open_recolor_target_in_editor_requested = Signal(str, object, object)

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
        self.current_preview_image: Optional[RecolorVariantPreviewImage] = None
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

        results_widget = QWidget()
        results_layout = QVBoxLayout(results_widget)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.setSpacing(8)
        results_widget.setMinimumWidth(320)
        self.splitter.addWidget(results_widget)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setStretchFactor(2, 1)
        self.splitter.setSizes(build_responsive_splitter_sizes(1680, [22, 52, 26], [340, 660, 360]))

        self._build_source_section(controls_layout)
        self._build_template_section(controls_layout)
        self._build_output_section(controls_layout)
        self._build_results_section(results_layout)

        self.summary_label = QLabel("Choose a loose or zip mod, then analyze it for safe recolor targets.")
        self.summary_label.setObjectName("HintLabel")
        self.summary_label.setWordWrap(True)
        main_layout.addWidget(self.summary_label)

        self.preview_summary_label = QLabel("Preview a template to see the exact texture and material-color impact before building.")
        self.preview_summary_label.setObjectName("RecolorVariantPreviewSummary")
        self.preview_summary_label.setWordWrap(True)
        main_layout.addWidget(self.preview_summary_label)

        self._build_selected_preview_section(main_layout)

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
        self.targets_tree.itemSelectionChanged.connect(self._handle_target_selection_changed)
        main_layout.addWidget(self.targets_tree, stretch=3)

        self.empty_state = EmptyStatePanel(
            "No analysis loaded",
            "Analyze a Source Mod to show safe basecolor/overlay texture slots and locked technical maps.",
            compact=True,
        )
        self.empty_state.setVisible(True)
        main_layout.addWidget(self.empty_state)

        self._reload_template_combo()
        self._load_settings()
        self._sync_template_editor()
        self._sync_action_state()

    def _build_results_section(self, parent_layout: QVBoxLayout) -> None:
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
        parent_layout.addWidget(outputs_group, stretch=2)

        log_group = FlatSectionPanel("Build Log", body_margins=(8, 8, 8, 8), body_spacing=6)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setObjectName("RecolorVariantBuildLog")
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(2000)
        log_group.body_layout.addWidget(self.log_edit)
        parent_layout.addWidget(log_group, stretch=3)

    def _build_selected_preview_section(self, parent_layout: QVBoxLayout) -> None:
        section = FlatSectionPanel("Selected Preview", body_margins=(8, 8, 8, 8), body_spacing=6)
        self.selected_target_label = QLabel("Select an editable DDS target, then refresh the preview.")
        self.selected_target_label.setObjectName("RecolorVariantSelectedTarget")
        self.selected_target_label.setWordWrap(True)
        section.body_layout.addWidget(self.selected_target_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        self.refresh_selected_preview_button = QPushButton("Refresh Preview")
        self.open_selected_in_editor_button = QPushButton("Open In Editor")
        actions.addWidget(self.refresh_selected_preview_button)
        actions.addWidget(self.open_selected_in_editor_button)
        actions.addStretch(1)
        section.body_layout.addLayout(actions)

        image_row = QHBoxLayout()
        image_row.setContentsMargins(0, 0, 0, 0)
        image_row.setSpacing(8)
        self.preview_source_image_label = _RecolorPreviewLabel("Before")
        self.preview_source_image_label.setObjectName("RecolorVariantBeforePreview")
        self.preview_result_image_label = _RecolorPreviewLabel("After")
        self.preview_result_image_label.setObjectName("RecolorVariantAfterPreview")
        for label in (self.preview_source_image_label, self.preview_result_image_label):
            image_row.addWidget(label, stretch=1)
        section.body_layout.addLayout(image_row, stretch=1)

        self.material_preview_widget = QWidget()
        material_layout = QHBoxLayout(self.material_preview_widget)
        material_layout.setContentsMargins(0, 0, 0, 0)
        material_layout.setSpacing(8)
        self.material_current_swatch = QLabel("Current")
        self.material_target_swatch = QLabel("Target")
        for label in (self.material_current_swatch, self.material_target_swatch):
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumHeight(34)
            material_layout.addWidget(label, stretch=1)
        self.material_preview_widget.setVisible(False)
        section.body_layout.addWidget(self.material_preview_widget)

        self.refresh_selected_preview_button.clicked.connect(self.refresh_selected_preview)
        self.open_selected_in_editor_button.clicked.connect(self.open_selected_target_in_editor)
        parent_layout.addWidget(section, stretch=5)

    def _build_source_section(self, parent_layout: QVBoxLayout) -> None:
        section = FlatSectionPanel("Source Mod", body_margins=(10, 10, 10, 10), body_spacing=8)
        section.header_widget.setVisible(False)
        layout = QGridLayout()
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)
        layout.setColumnStretch(1, 1)
        self.source_path_edit = QLineEdit()
        self.source_path_edit.setPlaceholderText("Folder or .zip package")
        self.source_browse_button = QPushButton("Browse")
        self.analyze_button = QPushButton("Analyze Mod")
        layout.addWidget(QLabel("Source Mod"), 0, 0)
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

    def _build_color_row(self, line_edit: QLineEdit, tooltip: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        button = QPushButton()
        button.setObjectName("RecolorVariantColorPickerButton")
        button.setToolTip(tooltip)
        button.setFixedWidth(34)
        layout.addWidget(button)
        layout.addWidget(line_edit, stretch=1)
        line_edit.textChanged.connect(lambda _text, edit=line_edit, picker=button: self._sync_color_picker_button(edit, picker))
        button.clicked.connect(lambda _checked=False, edit=line_edit: self._pick_color_into(edit))
        self._sync_color_picker_button(line_edit, button)
        return row

    def _build_slider_row(self, slider: QSlider, value_label: QLabel, *, suffix: str = "") -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value_label.setMinimumWidth(42)
        slider.valueChanged.connect(lambda value, label=value_label, unit=suffix: label.setText(f"{value}{unit}"))
        layout.addWidget(slider, stretch=1)
        layout.addWidget(value_label)
        return row

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
        self.source_color_row = self._build_color_row(self.source_color_edit, "Pick source color")
        self.target_color_row = self._build_color_row(self.target_color_edit, "Pick target color")
        self.tolerance_slider = QSlider(Qt.Horizontal)
        self.tolerance_slider.setRange(0, 255)
        self.tolerance_slider.setValue(48)
        self.tolerance_value_label = QLabel("48")
        self.tolerance_row = self._build_slider_row(self.tolerance_slider, self.tolerance_value_label)
        self.strength_slider = QSlider(Qt.Horizontal)
        self.strength_slider.setRange(1, 100)
        self.strength_slider.setValue(100)
        self.strength_value_label = QLabel("100%")
        self.strength_row = self._build_slider_row(self.strength_slider, self.strength_value_label, suffix="%")
        self.preserve_luma_checkbox = QCheckBox("Preserve shading / luminance")
        self.preserve_luma_checkbox.setChecked(True)
        self.import_template_button = QPushButton("Import JSON")
        self.export_template_button = QPushButton("Export JSON")
        self.save_template_button = QPushButton("Save Templates")
        self.preview_template_button = QPushButton("Review Matches")

        basic_rows = (
            ("Template", self.template_combo),
            ("Name", self.template_name_edit),
            ("Target color", self.target_color_row),
        )
        for row, (label, widget) in enumerate(basic_rows):
            layout.addWidget(QLabel(label), row, 0)
            layout.addWidget(widget, row, 1)
        advanced_section = CollapsibleSection("Advanced Template Filters", expanded=False)
        advanced_layout = QGridLayout()
        advanced_layout.setHorizontalSpacing(8)
        advanced_layout.setVerticalSpacing(8)
        advanced_layout.setColumnStretch(1, 1)
        advanced_rows = (
            ("Target kind", self.target_kind_combo),
            ("Slot kind", self.slot_kind_combo),
            ("Texture glob", self.filename_glob_edit),
            ("Material parameter", self.parameter_glob_edit),
            ("Operation", self.operation_combo),
            ("Source color", self.source_color_row),
            ("Tolerance", self.tolerance_row),
            ("Strength", self.strength_row),
        )
        for row, (label, widget) in enumerate(advanced_rows):
            advanced_layout.addWidget(QLabel(label), row, 0)
            advanced_layout.addWidget(widget, row, 1)
        advanced_layout.addWidget(self.preserve_luma_checkbox, len(advanced_rows), 1)
        advanced_section.body_layout.addLayout(advanced_layout)
        layout.addWidget(advanced_section, len(basic_rows), 0, 1, 2)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        actions.addWidget(self.import_template_button)
        actions.addWidget(self.export_template_button)
        actions.addWidget(self.save_template_button)
        actions.addWidget(self.preview_template_button)
        layout.addLayout(actions, len(basic_rows) + 1, 1)
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
        self.overwrite_checkbox.setToolTip("This only clears generated output folders. The Source Mod is never modified in place.")
        self.build_button = QPushButton("Build Variants")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.open_output_button = QPushButton("Open Output Folder")
        self.profile_checkboxes: Dict[str, QCheckBox] = {}
        profiles_group = CollapsibleSection("Manager outputs", expanded=False)
        profiles_layout = profiles_group.body_layout
        for profile_id, label, checked in (
            ("dmm", "Definitive Mod Manager", True),
            ("jmm", "JMM JSON", False),
            ("cdumm", "CDUMM files/ wrapper", False),
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
        self.tolerance_slider.setValue(rule.tolerance)
        self.strength_slider.setValue(rule.strength)
        self.preserve_luma_checkbox.setChecked(rule.preserve_luminance)
        self._sync_template_kind_controls()

    def _sync_template_kind_controls(self) -> None:
        texture_mode = str(self.target_kind_combo.currentData() or "texture_slot") == "texture_slot"
        self.slot_kind_combo.setEnabled(texture_mode)
        self.filename_glob_edit.setEnabled(texture_mode)
        self.parameter_glob_edit.setEnabled(not texture_mode)
        self.tolerance_row.setEnabled(texture_mode)
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
            tolerance=self.tolerance_slider.value(),
            strength=self.strength_slider.value(),
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
            self.status_message_requested.emit("Choose a Source Mod folder or zip first.", True)
            return
        source = Path(source_text).expanduser()
        if not source.exists():
            self.status_message_requested.emit(f"Source Mod not found: {source}", True)
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
            self._handle_target_selection_changed()
            return
        first_editable_item: Optional[QTreeWidgetItem] = None
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
            item.setData(0, Qt.UserRole, target.target_id)
            if not target.editable:
                item.setForeground(4, Qt.GlobalColor.darkYellow)
            elif first_editable_item is None:
                first_editable_item = item
            self.targets_tree.addTopLevelItem(item)
        self.empty_state.setVisible(self.targets_tree.topLevelItemCount() == 0)
        if first_editable_item is not None:
            self.targets_tree.setCurrentItem(first_editable_item)
        else:
            self._handle_target_selection_changed()

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
            self.status_message_requested.emit("Analyze a Source Mod first.", True)
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

    def _selected_target(self):
        if self.analysis is None:
            return None
        item = self.targets_tree.currentItem()
        target_id = str(item.data(0, Qt.UserRole) or "") if item is not None else ""
        if not target_id:
            return None
        return next((target for target in self.analysis.targets if target.target_id == target_id), None)

    def _matching_rule_for_target(self, target) -> Optional[RecolorVariantRule]:
        return matching_recolor_variant_rule(target, self._template_from_controls().rules)

    def _handle_target_selection_changed(self) -> None:
        self.current_preview_image = None
        self._clear_preview_images()
        target = self._selected_target()
        if target is None:
            self.selected_target_label.setText("Select an editable DDS target, then refresh the preview.")
            self.material_preview_widget.setVisible(False)
            self._sync_action_state()
            return
        state = "editable" if target.editable else f"locked: {target.locked_reason or 'not editable'}"
        self.selected_target_label.setText(f"{target.game_path} ({target.target_kind}, {state})")
        if target.target_kind == "material_color":
            rule = self._matching_rule_for_target(target)
            target_color = rule.target_color if rule is not None else "#C85A30"
            self._set_color_swatch(self.material_current_swatch, target.current_value, "Current")
            self._set_color_swatch(self.material_target_swatch, target_color, "Target")
            self.material_preview_widget.setVisible(True)
            self.preview_source_image_label.setText("Material color")
            self.preview_result_image_label.setText("Open DDS preview unavailable")
        else:
            self.material_preview_widget.setVisible(False)
        self._sync_action_state()

    def _clear_preview_images(self) -> None:
        for label, text in (
            (self.preview_source_image_label, "Before"),
            (self.preview_result_image_label, "After"),
        ):
            if isinstance(label, _RecolorPreviewLabel):
                label.set_placeholder(text)
            else:
                label.clear()
                label.setText(text)

    def _set_color_swatch(self, label: QLabel, color_text: str, caption: str) -> None:
        color = self._qcolor_from_text(color_text)
        if color.isValid():
            label.setText(f"{caption}: {color.name().upper()}")
            label.setStyleSheet(f"QLabel {{ background-color: {color.name()}; color: {self._swatch_text_color(color)}; border: 1px solid palette(mid); }}")
        else:
            label.setText(f"{caption}: {color_text or 'unknown'}")
            label.setStyleSheet("QLabel { border: 1px solid palette(mid); }")

    def _sync_color_picker_button(self, line_edit: QLineEdit, button: QPushButton) -> None:
        color = self._qcolor_from_text(line_edit.text())
        if color.isValid():
            button.setText("")
            button.setStyleSheet(f"QPushButton {{ background-color: {color.name()}; border: 1px solid palette(mid); }}")
        else:
            button.setText("...")
            button.setStyleSheet("")

    def _pick_color_into(self, line_edit: QLineEdit) -> None:
        current = self._qcolor_from_text(line_edit.text())
        if not current.isValid():
            current = QColor("#C85A30")
        selected = QColorDialog.getColor(current, self, "Choose recolor color")
        if selected.isValid():
            line_edit.setText(selected.name().upper())

    def _qcolor_from_text(self, color_text: str) -> QColor:
        text = str(color_text or "").strip()
        if len(text) == 9 and text.startswith("#"):
            text = text[:7]
        return QColor(text)

    def _swatch_text_color(self, color: QColor) -> str:
        luma = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
        return "#000000" if luma > 150 else "#ffffff"

    def _set_preview_pixmap(self, label: QLabel, path: Path, fallback: str) -> None:
        if isinstance(label, _RecolorPreviewLabel):
            label.set_preview_path(path, fallback)
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            label.clear()
            label.setText(fallback)
            return
        label.setPixmap(pixmap.scaled(label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _texture_editor_settings_for_rule(self, rule: RecolorVariantRule) -> TextureEditorToolSettings:
        return texture_editor_settings_for_recolor_variant_rule(rule)

    def refresh_selected_preview(self) -> None:
        target = self._selected_target()
        if target is None:
            self.status_message_requested.emit("Select a recolor target first.", True)
            return
        if target.target_kind != "texture_slot":
            self.status_message_requested.emit("Material color targets use swatches instead of DDS preview.", False)
            return
        texconv_text = self.get_texconv_path().strip()
        texconv_path = Path(texconv_text).expanduser() if texconv_text else None
        if texconv_path is not None and not texconv_path.is_file():
            texconv_path = None
        try:
            self.current_preview_image = preview_recolor_variant_target_image(
                self.analysis,
                self._template_from_controls(),
                target.target_id,
                texconv_path=texconv_path,
            )
        except Exception as exc:
            self.current_preview_image = None
            self._clear_preview_images()
            self.status_message_requested.emit(f"Recolor preview failed: {exc}", True)
            return
        self._set_preview_pixmap(self.preview_source_image_label, self.current_preview_image.source_png, "Before unavailable")
        self._set_preview_pixmap(self.preview_result_image_label, self.current_preview_image.preview_png, "After unavailable")
        for warning in self.current_preview_image.warnings:
            self._append_log(f"Warning: {warning}")
        self.status_message_requested.emit("Selected recolor preview updated.", False)
        self._sync_action_state()

    def open_selected_target_in_editor(self) -> None:
        target = self._selected_target()
        if target is None:
            self.status_message_requested.emit("Select a recolor target first.", True)
            return
        if target.target_kind != "texture_slot":
            self.status_message_requested.emit("Only DDS texture targets can open in Texture Editor.", True)
            return
        if self.current_preview_image is None or self.current_preview_image.target_id != target.target_id:
            self.refresh_selected_preview()
        if self.current_preview_image is None:
            return
        rule = self._matching_rule_for_target(target)
        if rule is None:
            self.status_message_requested.emit("Current recolor template does not match the selected texture target.", True)
            return
        binding = TextureEditorSourceBinding(
            launch_origin="recolor_variants",
            display_name=target.label or Path(target.game_path).name,
            source_path=str(self.current_preview_image.source_dds_path),
            source_identity_path=f"{self.analysis.package_path}:{target.game_path}" if self.analysis is not None else str(self.current_preview_image.source_dds_path),
            relative_path=target.game_path,
            archive_relative_path=target.game_path,
            original_dds_path=str(self.current_preview_image.source_dds_path),
            original_texconv_format=target.texconv_format,
            texture_type=target.texture_type,
            semantic_subtype=target.semantic_subtype,
        )
        self.open_recolor_target_in_editor_requested.emit(
            str(self.current_preview_image.source_dds_path),
            binding,
            self._texture_editor_settings_for_rule(rule),
        )
        self.status_message_requested.emit("Opened selected recolor target in Texture Editor.", False)

    def _selected_profiles(self) -> tuple[RecolorVariantOutputProfile, ...]:
        profiles: list[RecolorVariantOutputProfile] = []
        labels = {
            "cdumm": "CDUMM",
            "jmm": "JMM JSON",
            "dmm": "Definitive Mod Manager",
            "crimson_sharp": "Crimson Sharp",
            "field_json": "Field-JSON v3.1",
        }
        suffixes = {
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
            self.status_message_requested.emit("Analyze a Source Mod first.", True)
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
        self._append_log("Starting recolor variant build. Source Mod will not be modified in place.")
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
        target = self._selected_target() if self.analysis is not None else None
        texture_target = target is not None and target.target_kind == "texture_slot" and target.editable
        self.refresh_selected_preview_button.setEnabled(bool(texture_target) and not busy)
        self.open_selected_in_editor_button.setEnabled(bool(texture_target) and not busy)
        if target is not None and target.target_kind == "material_color":
            self.open_selected_in_editor_button.setToolTip("Material color targets show swatches here; Texture Editor opens DDS images only.")
        elif target is not None and not target.editable:
            self.open_selected_in_editor_button.setToolTip(target.locked_reason or "Selected target is locked.")
        else:
            self.open_selected_in_editor_button.setToolTip("")
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
