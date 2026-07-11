"""Retrofit/Repackage widget construction and UI-only state."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.packages.export_policy import (
    MOD_PACKAGE_MANAGER_PROFILE_LABELS,
    ModPackageExportOptions,
    mod_package_export_options_for_manager,
    mod_package_profile_uses_manager_metadata,
)
from cdmw.domain.packages.retrofit import (
    RETROFIT_MANAGER_PROFILES,
    RetrofitPathRepairSummary,
    RetrofittableModPackage,
)
from cdmw.ui.tools.mod_package_retrofit_tasks import retrofit_task_controller_for_widget
from cdmw.ui.tools.mod_package_retrofit_view import (
    build_retrofit_processing_results_html,
    build_retrofit_update_plan_html,
    retrofit_readiness_for_summary,
    retrofit_readiness_label_for_summary,
    retrofit_scan_readiness_summary,
    retrofit_selection_readiness_summary,
)
from cdmw.workers.mod_package_retrofit_workers import (
    RetrofitConversionItem,
    RetrofitConversionRequest,
    RetrofitConversionResult,
    RetrofitScanResult,
)


class ModPackageRetrofitUi:
    def __init__(
        self,
        owner: object,
        parent: QWidget,
        *,
        on_close: Callable[[], None] | None,
    ) -> None:
        self.owner = owner
        self.parent = parent
        self.on_close = on_close
        self.dialog_title = "Retrofit/Repackage Mods"
        self.task_controller = retrofit_task_controller_for_widget(owner, parent)  # type: ignore[arg-type]
        self.packages: list[RetrofittableModPackage] = []
        self.summaries: list[RetrofitPathRepairSummary] = []
        self.empty_summary = RetrofitPathRepairSummary(mappings=tuple())
        self.profile_labels = dict(MOD_PACKAGE_MANAGER_PROFILE_LABELS)
        self.profile_labels["dmm"] = "Mod Manager"
        self.profile_labels["crimson_sharp"] = "Crimson Sharp / Crimson Browser"
        config = owner.collect_config()  # type: ignore[attr-defined]
        self.default_profile = str(getattr(config, "mod_ready_manager_profile", "dmm") or "dmm").strip().lower()
        if self.default_profile not in RETROFIT_MANAGER_PROFILES:
            self.default_profile = "dmm"

    def build(self, *, run_initial_scan: bool) -> None:
        self.layout = QVBoxLayout(self.parent)
        self.layout.setContentsMargins(12, 12, 12, 12)
        self.layout.setSpacing(10)
        self._build_header_and_paths()
        self._build_content()
        self._build_actions()
        self._connect_signals()
        self.selection_status_label.setText("No packages selected.")
        self.convert_button.setEnabled(False)
        if run_initial_scan:
            self._scan()
        self._apply_widget_localization(self.parent)

    def _build_header_and_paths(self) -> None:
        if self.on_close is not None:
            title = QLabel(self.dialog_title)
            title.setObjectName("SectionTitle")
            self.layout.addWidget(title)
        intro = QLabel(
            "Scan loose or zipped mod packages and repackage them for another supported mod-manager profile. "
            "Use checkboxes to process one package or many at once."
        )
        intro.setWordWrap(True)
        intro.setObjectName("HintLabel")
        self.layout.addWidget(intro)

        config = self.owner.collect_config()  # type: ignore[attr-defined]
        configured_root = str(getattr(config, "mod_ready_export_root", "") or "").strip()
        settings_path = Path(self.owner.settings_file_path)  # type: ignore[attr-defined]
        source_default = Path(configured_root).expanduser() if configured_root else settings_path.parent
        self.source_edit = QLineEdit(str(source_default))
        self.source_edit.setObjectName("retrofit_source_edit")
        self.output_edit = QLineEdit(str(source_default / "converted"))
        self.output_edit.setObjectName("retrofit_output_edit")
        self.browse_source_button = QPushButton("Browse...")
        self.browse_output_button = QPushButton("Browse...")
        self.scan_button = QPushButton("Scan")
        self.scan_button.setObjectName("retrofit_scan_button")
        hint = QLabel(
            "Choose a target profile per row, such as Mod Manager, CDUMM, JMM JSON, Crimson Sharp, or Field JSON."
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)

        path_layout = QGridLayout()
        path_layout.setHorizontalSpacing(8)
        path_layout.setVerticalSpacing(8)
        path_layout.addWidget(QLabel("Source folder"), 0, 0)
        path_layout.addWidget(self.source_edit, 0, 1)
        path_layout.addWidget(self.browse_source_button, 0, 2)
        path_layout.addWidget(QLabel("Output folder"), 1, 0)
        path_layout.addWidget(self.output_edit, 1, 1)
        path_layout.addWidget(self.browse_output_button, 1, 2)
        path_layout.addWidget(self.scan_button, 0, 3, 2, 1)
        path_layout.addWidget(hint, 2, 1, 1, 2)
        path_layout.setColumnStretch(1, 1)
        self.layout.addLayout(path_layout)

    def _build_content(self) -> None:
        self.content_splitter = QSplitter(Qt.Horizontal)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setHandleWidth(8)
        self.layout.addWidget(self.content_splitter, 1)

        left_panel = QWidget()
        left_panel.setMinimumWidth(540)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        self.content_splitter.addWidget(left_panel)
        right_panel = QWidget()
        right_panel.setMinimumWidth(420)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        self.content_splitter.addWidget(right_panel)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 1)

        self.table = self._create_table()
        left_layout.addWidget(self.table, 1)
        self.scan_summary_label = QLabel("Scan to see package readiness summary.")
        self.scan_summary_label.setObjectName("HintLabel")
        self.scan_summary_label.setWordWrap(True)
        left_layout.addWidget(self.scan_summary_label)
        legend = QLabel(
            "Status: Ready packages can be rewritten for the selected manager profile; warnings need review before processing."
        )
        legend.setObjectName("HintLabel")
        legend.setWordWrap(True)
        left_layout.addWidget(legend)
        self.status_label = QLabel("Scan a source folder to find packaged mods.")
        self.status_label.setObjectName("HintLabel")
        left_layout.addWidget(self.status_label)

        diff_label = QLabel("Retrofit/Repackage plan for selected packages")
        diff_label.setObjectName("HintLabel")
        diff_label.setWordWrap(True)
        self.diff_preview = QTextBrowser()
        self.diff_preview.setReadOnly(True)
        self.diff_preview.setOpenExternalLinks(False)
        self.diff_preview.setMinimumWidth(360)
        self.diff_preview.setHtml(
            "<p>Select package rows and press <strong>Preview Package Plan</strong>, or read this live preview.</p>"
        )
        right_layout.addWidget(diff_label)
        right_layout.addWidget(self.diff_preview, 1)
        self.selection_status_label = QLabel("Select package rows and check a box to see package summary.")
        self.selection_status_label.setObjectName("HintLabel")
        self.selection_status_label.setWordWrap(True)
        right_layout.addWidget(self.selection_status_label)
        self.content_splitter.setSizes([700, 420])
        QTimer.singleShot(0, self._apply_content_splitter_sizes)
        QTimer.singleShot(120, self._apply_content_splitter_sizes)

    def _create_table(self) -> QTableWidget:
        table = QTableWidget(0, 12)
        table.setObjectName("retrofit_packages_table")
        table.setHorizontalHeaderLabels(
            [
                "Use", "Package", "Kind", "Existing metadata", "Payloads", "Manager profile",
                "Structure", "Conflict", "Language", "Ready zip", "Warnings", "Package status",
            ]
        )
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.ElideRight)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setMinimumWidth(0)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        table.verticalHeader().setVisible(False)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setMinimumHeight(260)
        table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        table.verticalHeader().setDefaultSectionSize(28)
        header = table.horizontalHeader()
        header.setSectionsMovable(True)
        header.setMinimumSectionSize(70)
        header.setStretchLastSection(False)
        for column in range(table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
        for column, width in enumerate((50, 360, 110, 150, 84, 170, 180, 130, 110, 70, 260, 190)):
            table.setColumnWidth(column, width)
        return table

    def _build_actions(self) -> None:
        button_row = QHBoxLayout()
        self.preview_button = QPushButton("Preview Package Plan")
        self.convert_button = QPushButton("Process Selected")
        self.convert_button.setObjectName("retrofit_convert_button")
        self.open_output_button = QPushButton("Open Output Folder")
        button_row.addWidget(self.preview_button)
        button_row.addWidget(self.convert_button)
        button_row.addWidget(self.open_output_button)
        button_row.addStretch(1)
        self.close_button = QPushButton("Close") if self.on_close is not None else None
        if self.close_button is not None:
            button_row.addWidget(self.close_button)
        self.layout.addLayout(button_row)

    def _connect_signals(self) -> None:
        self.browse_source_button.clicked.connect(self._browse_source)
        self.browse_output_button.clicked.connect(self._browse_output)
        self.scan_button.clicked.connect(self._scan)
        self.preview_button.clicked.connect(self._preview_plan)
        self.convert_button.clicked.connect(self._convert_selected)
        self.open_output_button.clicked.connect(self._open_output)
        self.task_controller.scan_completed.connect(self._handle_scan_completed)
        self.task_controller.conversion_completed.connect(self._handle_conversion_completed)
        self.task_controller.failed.connect(self._handle_task_failed)
        self.task_controller.progress.connect(self._handle_task_progress)
        self.task_controller.busy_changed.connect(self._handle_task_busy)
        if self.close_button is not None and self.on_close is not None:
            self.close_button.clicked.connect(self.on_close)
        self.table.itemSelectionChanged.connect(self._refresh_diff_preview)
        self.table.itemChanged.connect(self._handle_table_item_changed)

    def _apply_content_splitter_sizes(self) -> None:
        width = max(1, self.content_splitter.width())
        left_width = max(540, int(width * 0.56))
        right_width = max(420, width - left_width)
        if left_width + right_width > width:
            left_width = max(540, width - right_width)
        self.content_splitter.setSizes([left_width, right_width])

    def _apply_widget_localization(self, widget: QWidget) -> None:
        apply_localizer = getattr(getattr(self.owner, "ui_localizer", None), "apply", None)
        if callable(apply_localizer):
            apply_localizer(widget)

    def _selected_rows(self) -> list[int]:
        return [
            row
            for row in range(self.table.rowCount())
            if self.table.item(row, 0) is not None and self.table.item(row, 0).checkState() == Qt.Checked
        ]

    def _summary_for_row(self, row: int) -> RetrofitPathRepairSummary:
        return self.summaries[row] if 0 <= row < len(self.summaries) else self.empty_summary

    def _manager_for_row(self, row: int) -> str:
        combo = self.table.cellWidget(row, 5)
        return str(combo.currentData() or "dmm") if isinstance(combo, QComboBox) else "dmm"

    def _combo_data(self, row: int, column: int) -> str:
        combo = self.table.cellWidget(row, column)
        return str(combo.currentData() or "") if isinstance(combo, QComboBox) else ""

    def _ready_zip_for_row(self, row: int) -> bool:
        checkbox = self.table.cellWidget(row, 9)
        return checkbox.isChecked() if isinstance(checkbox, QCheckBox) else True

    def _export_options_for_row(self, row: int) -> ModPackageExportOptions:
        profile = self._manager_for_row(row)
        defaults = mod_package_export_options_for_manager(profile)
        uses_metadata = mod_package_profile_uses_manager_metadata(profile)
        language = self.table.cellWidget(row, 8)
        return ModPackageExportOptions(
            manager_targets=tuple(defaults.manager_targets),
            structure=self._combo_data(row, 6) or defaults.structure,
            create_manifest_json=defaults.create_manifest_json,
            create_mod_json=defaults.create_mod_json,
            create_modinfo_json=defaults.create_modinfo_json,
            create_info_json=defaults.create_info_json,
            create_no_encrypt_file=defaults.create_no_encrypt_file,
            create_zip=self._ready_zip_for_row(row),
            conflict_mode=self._combo_data(row, 7) if uses_metadata else "",
            target_language=language.text().strip() if uses_metadata and isinstance(language, QLineEdit) else "",
            files_dir=defaults.files_dir,
        )

    def _apply_profile_defaults(self, row: int) -> None:
        profile = self._manager_for_row(row)
        defaults = mod_package_export_options_for_manager(profile)
        structure = self.table.cellWidget(row, 6)
        if isinstance(structure, QComboBox):
            index = structure.findData(defaults.structure)
            if index >= 0:
                structure.setCurrentIndex(index)
            structure.setEnabled(profile not in {"jmm", "field_json"})
        uses_metadata = mod_package_profile_uses_manager_metadata(profile)
        for column in (7, 8):
            widget = self.table.cellWidget(row, column)
            if widget is not None:
                widget.setEnabled(uses_metadata)

    def _build_plan_html(self, rows: Sequence[int], output_root: Path, max_rows: int) -> str:
        return build_retrofit_update_plan_html(
            rows,
            packages=self.packages,
            package_repair_summaries=self.summaries,
            update_mode=False,
            archive_index_size=0,
            profiles_by_row={row: self._manager_for_row(row) for row in rows},
            profile_labels=self.profile_labels,
            output_root=output_root,
            max_rows_per_package=max_rows,
        )

    def _refresh_diff_preview(self) -> None:
        rows = self._selected_rows()
        if not rows:
            self.diff_preview.setHtml("<p>No packages selected. Check package rows to inspect the selected operation plan.</p>")
            self.selection_status_label.setText("No packages selected.")
            return
        self.diff_preview.setHtml(self._build_plan_html(rows, Path(self.output_edit.text().strip()).expanduser(), 12))
        self.selection_status_label.setText(
            retrofit_selection_readiness_summary(rows, summaries=self.summaries, update_mode=False)
        )

    def _set_cell(self, row: int, column: int, value: str) -> None:
        text = value or "-"
        item = QTableWidgetItem(text)
        item.setToolTip(text)
        self.table.setItem(row, column, item)

    def _add_package_row(self, package: RetrofittableModPackage) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        use_item = QTableWidgetItem("")
        use_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        use_item.setCheckState(Qt.Checked)
        self.table.setItem(row, 0, use_item)
        self._set_cell(row, 1, package.name)
        self._set_cell(row, 2, package.kind)
        self._set_cell(row, 3, ", ".join(package.existing_metadata))
        self._set_cell(row, 4, str(len(package.payload_paths)))
        self._add_row_controls(row)
        self._set_cell(row, 10, "; ".join(package.warnings))
        summary = self._summary_for_row(row)
        label = retrofit_readiness_label_for_summary(summary, update_mode=False)
        _text, detail, color = retrofit_readiness_for_summary(summary, update_mode=False)
        status_item = QTableWidgetItem(label)
        status_item.setToolTip(detail)
        status_item.setForeground(QBrush(QColor(color)))
        self.table.setItem(row, 11, status_item)

    def _add_row_controls(self, row: int) -> None:
        manager = QComboBox()
        for profile in RETROFIT_MANAGER_PROFILES:
            manager.addItem(self.profile_labels.get(profile, profile), profile)
        default_index = manager.findData(self.default_profile)
        if default_index >= 0:
            manager.setCurrentIndex(default_index)
        manager.setToolTip("Choose the manager profile to generate for this package.")
        self._apply_widget_localization(manager)
        self.table.setCellWidget(row, 5, manager)
        structure = QComboBox()
        for label, value in (
            ("Game-relative folders", "game_relative"), ("files/ wrapper", "files_wrapper"),
            ("Custom compact paths", "custom_compact_paths"), ("DMM texture folder", "dmm_texture"),
            ("Field-JSON v3.1 assets", "field_json_v31"),
        ):
            structure.addItem(label, value)
        self._apply_widget_localization(structure)
        self.table.setCellWidget(row, 6, structure)
        conflict = QComboBox()
        conflict.addItem("Normal", "")
        conflict.addItem("Override wins", "override")
        self._apply_widget_localization(conflict)
        self.table.setCellWidget(row, 7, conflict)
        language = QLineEdit()
        language.setPlaceholderText("Optional")
        self._apply_widget_localization(language)
        self.table.setCellWidget(row, 8, language)
        ready_zip = QCheckBox()
        ready_zip.setChecked(True)
        ready_zip.setToolTip("Write rebuilt zip beside the converted folder.")
        self._apply_widget_localization(ready_zip)
        self.table.setCellWidget(row, 9, ready_zip)
        manager.currentIndexChanged.connect(lambda _index, table_row=row: self._apply_profile_defaults(table_row))
        self._apply_profile_defaults(row)

    def _populate_table(self) -> None:
        self.table.setRowCount(0)
        title, text = retrofit_scan_readiness_summary(
            package_count=len(self.packages), summaries=self.summaries, update_mode=False
        )
        self.scan_summary_label.setText(f"{title}: {text}")
        for package in self.packages:
            self._add_package_row(package)
        self.status_label.setText(f"Found {len(self.packages):,} packaged mod folder(s).")
        self._refresh_diff_preview()

    def _scan(self) -> None:
        source = Path(self.source_edit.text().strip()).expanduser()
        if not self.output_edit.text().strip():
            self.output_edit.setText(str(source / "converted"))
        if self.task_controller.start_scan(source):
            self.status_label.setText("Scanning packaged mods...")

    def _handle_scan_completed(self, result: object) -> None:
        if not isinstance(result, RetrofitScanResult):
            return
        self.packages[:] = result.packages
        self.summaries[:] = result.summaries
        self._populate_table()

    def _handle_task_failed(self, kind: str, message: str) -> None:
        action = "scan" if kind == "scan" else "conversion"
        self.status_label.setText(f"Retrofit {action} failed: {message}")
        QMessageBox.warning(self.parent, self.dialog_title, str(message))

    def _handle_task_progress(self, kind: str, current: int, total: int, detail: str) -> None:
        prefix = "Scanning" if kind == "scan" else "Processing"
        count = f" ({current:,}/{total:,})" if total > 0 else ""
        self.status_label.setText(f"{prefix}{count}: {detail}")

    def _handle_task_busy(self, scan_busy: bool, conversion_busy: bool) -> None:
        self.scan_button.setEnabled(not conversion_busy)
        self.convert_button.setEnabled(bool(self.packages) and not scan_busy and not conversion_busy)

    def _browse_source(self) -> None:
        selected = QFileDialog.getExistingDirectory(self.parent, "Choose packaged mods folder", self.source_edit.text().strip())
        if selected:
            self.source_edit.setText(selected)
            self.output_edit.setText(str(Path(selected).expanduser() / "converted"))

    def _browse_output(self) -> None:
        selected = QFileDialog.getExistingDirectory(self.parent, "Choose converted output folder", self.output_edit.text().strip())
        if selected:
            self.output_edit.setText(selected)

    def _preview_plan(self) -> None:
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self.parent, self.dialog_title, "Select at least one package to preview.")
            return
        self.diff_preview.setHtml(self._build_plan_html(rows, Path(self.output_edit.text().strip()).expanduser(), 28))

    def _convert_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self.parent, self.dialog_title, "Select at least one package to process.")
            return
        items = tuple(
            RetrofitConversionItem(
                package=self.packages[row],
                manager_profile=self._manager_for_row(row),
                export_options=self._export_options_for_row(row),
                scan_summary=self._summary_for_row(row),
            )
            for row in rows
        )
        request = RetrofitConversionRequest(0, Path(self.output_edit.text().strip()).expanduser(), items)
        if self.task_controller.start_conversion(request):
            self.status_label.setText(f"Processing {len(items):,} selected package(s)...")

    def _handle_conversion_completed(self, result: object) -> None:
        if not isinstance(result, RetrofitConversionResult):
            return
        self.status_label.setText(
            f"Processed {len(result.processed):,} package(s). Failed {len(result.failed):,} package(s)."
            if result.processed or result.failed else "No packages were selected for processing."
        )
        dialog = QDialog(self.parent)
        dialog.setWindowTitle(self.dialog_title)
        dialog.resize(880, 620)
        layout = QVBoxLayout(dialog)
        details = QTextBrowser()
        details.setReadOnly(True)
        details.setHtml(build_retrofit_processing_results_html(result.processed, result.failed, update_mode=False))
        details.setMinimumHeight(430)
        layout.addWidget(details)
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, alignment=Qt.AlignRight)
        dialog.exec()

    def _open_output(self) -> None:
        output_root = Path(self.output_edit.text().strip()).expanduser()
        output_root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_root)))

    def _handle_table_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 0:
            self._refresh_diff_preview()


def build_mod_package_retrofit_tool(
    owner: object,
    parent: QWidget,
    *,
    run_initial_scan: bool,
    on_close: Callable[[], None] | None = None,
) -> ModPackageRetrofitUi:
    ui = ModPackageRetrofitUi(owner, parent, on_close=on_close)
    ui.build(run_initial_scan=run_initial_scan)
    setattr(parent, "_retrofit_ui", ui)
    return ui


__all__ = ["ModPackageRetrofitUi", "build_mod_package_retrofit_tool"]
