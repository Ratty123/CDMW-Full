from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
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

from cdmw.core.mod_package import (
    MOD_PACKAGE_MANAGER_PROFILE_LABELS,
    ModPackageExportOptions,
    mod_package_export_options_for_manager,
    mod_package_profile_uses_manager_metadata,
)
from cdmw.core.mod_package_retrofit import (
    RETROFIT_MANAGER_PROFILES,
    RetrofitPathRepairSummary,
    RetrofittableModPackage,
    build_retrofit_path_repair_summary,
    retrofit_mod_package,
)
from cdmw.ui.tools.mod_package_retrofit_view import (
    build_retrofit_processing_results_html,
    build_retrofit_update_plan_html,
    collect_retrofittable_packages,
    next_available_retrofit_package_name,
    retrofit_game_build_from_root,
    retrofit_readiness_for_summary,
    retrofit_readiness_label_for_summary,
    retrofit_scan_readiness_summary,
    retrofit_selection_readiness_summary,
)


class ArchiveModPackageRetrofitDialogMixin:
    def _show_mod_package_retrofit_dialog(self) -> None:
        dialog_title = "Retrofit/Repackage Mods"
        dialog = QDialog(self)
        dialog.setWindowTitle(dialog_title)
        dialog.setModal(True)
        dialog.resize(1120, 760)
        self._build_mod_package_retrofit_tool(
            dialog,
            run_initial_scan=True,
            on_close=dialog.reject,
        )
        dialog.exec()

    def _build_mod_package_retrofit_tool(
        self,
        parent: QWidget,
        *,
        run_initial_scan: bool,
        on_close: Optional[Callable[[], None]] = None,
    ) -> None:
        dialog_title = "Retrofit/Repackage Mods"
        message_parent = parent

        layout = QVBoxLayout(parent)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel(dialog_title)
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        mode_blurb = (
            "This tool scans mod packages, compares selected packages against the loaded current game files in update mode, "
            "repairs stale paths/new_paths where possible, and repackages selected packages for supported mod-manager profiles."
        )
        intro = QLabel(
            f"{mode_blurb} "
            "Use repackage-only mode when you only want manager conversion without current-game compatibility checks."
        )
        intro.setWordWrap(True)
        intro.setObjectName("HintLabel")
        layout.addWidget(intro)

        configured_root = str(getattr(self.collect_config(), "mod_ready_export_root", "") or "").strip()
        source_default = Path(configured_root).expanduser() if configured_root else self.settings_file_path.parent
        source_edit = QLineEdit(str(source_default))
        output_edit = QLineEdit(str(source_default / "converted"))
        browse_source_button = QPushButton("Browse...")
        browse_output_button = QPushButton("Browse...")
        scan_button = QPushButton("Scan")
        refresh_index_button = QPushButton("Refresh Game Index")
        operation_combo = QComboBox()
        operation_combo.addItem("Update for current game version + repackage", "update")
        operation_combo.addItem("Repackage only (manager conversion)", "repackage")
        mode_hint_label = QLabel(
            "Update mode compares selected packages against the loaded current game files before repackaging."
        )
        mode_hint_label.setObjectName("HintLabel")
        mode_hint_label.setWordWrap(True)

        def _operation_mode() -> str:
            return str(operation_combo.currentData() or "update")

        def _is_update_mode() -> bool:
            return _operation_mode() == "update"

        def _hide_retrofit_clutter() -> None:
            return

        path_layout = QGridLayout()
        path_layout.setHorizontalSpacing(8)
        path_layout.setVerticalSpacing(8)
        path_layout.addWidget(QLabel("Operation"), 0, 0)
        path_layout.addWidget(operation_combo, 0, 1)
        path_layout.addWidget(mode_hint_label, 1, 1, 1, 2)
        path_layout.addWidget(QLabel("Source folder"), 2, 0)
        path_layout.addWidget(source_edit, 2, 1)
        path_layout.addWidget(browse_source_button, 2, 2)
        path_layout.addWidget(QLabel("Output folder"), 3, 0)
        path_layout.addWidget(output_edit, 3, 1)
        path_layout.addWidget(browse_output_button, 3, 2)
        path_layout.addWidget(scan_button, 2, 3, 2, 1)
        path_layout.addWidget(QLabel("Game file index"), 4, 0)
        path_layout.addWidget(refresh_index_button, 4, 3)
        path_layout.setColumnStretch(1, 1)
        game_build_label = QLabel("Game build")
        path_layout.addWidget(game_build_label, 5, 0)
        game_build_status_label = QLabel("Detecting current game build...")
        game_build_status_label.setObjectName("HintLabel")
        game_build_status_label.setWordWrap(False)
        game_build_status_label.setToolTip("Detected from the loaded archive/game files.")
        path_layout.addWidget(game_build_status_label, 5, 1, 1, 2)
        layout.addLayout(path_layout)

        def _detect_current_game_build() -> str:
            for entry in list(getattr(self, "archive_entries", ())):
                pamt_path = getattr(entry, "pamt_path", None)
                if isinstance(pamt_path, Path):
                    build = retrofit_game_build_from_root(pamt_path.parent.parent)
                    if build:
                        return build
            configured_root = Path(self.archive_package_root_edit.text().strip()) if self.archive_package_root_edit else Path()
            if configured_root.is_dir():
                build = retrofit_game_build_from_root(configured_root)
                if build:
                    return build
                for child in sorted(configured_root.iterdir(), key=lambda item: item.name.lower()):
                    if not child.is_dir() or child.name.startswith("."):
                        continue
                    build = retrofit_game_build_from_root(child)
                    if build:
                        return build
            return ""

        def _build_archive_index_status_text() -> str:
            if not _is_update_mode():
                return "Game archive index disabled in Repackage only mode."
            index_count = len(getattr(self, "archive_entries_by_basename", {}) or {})
            if index_count:
                return f"Loaded game archive index ({index_count:,} basenames)."
            return "Game archive index not loaded -- compact-path repair may be limited."

        archive_index_status_label = QLabel(_build_archive_index_status_text())
        archive_index_status_label.setObjectName("HintLabel")
        archive_index_status_label.setWordWrap(True)
        layout.addWidget(archive_index_status_label)

        content_splitter = QSplitter(Qt.Horizontal)
        content_splitter.setChildrenCollapsible(False)
        content_splitter.setHandleWidth(8)
        layout.addWidget(content_splitter, 1)

        left_panel = QWidget()
        left_panel.setMinimumWidth(540)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        content_splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_panel.setMinimumWidth(420)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        content_splitter.addWidget(right_panel)
        content_splitter.setStretchFactor(0, 1)
        content_splitter.setStretchFactor(1, 1)

        table = QTableWidget(0, 12)
        table.setHorizontalHeaderLabels(
            [
                "Use",
                "Package",
                "Kind",
                "Existing metadata",
                "Payloads",
                "Manager profile",
                "Structure",
                "Conflict",
                "Language",
                "Ready zip",
                "Warnings",
                "Update status",
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
        table.setColumnWidth(0, 50)
        table.setColumnWidth(1, 360)
        table.setColumnWidth(2, 110)
        table.setColumnWidth(3, 150)
        table.setColumnWidth(4, 84)
        table.setColumnWidth(5, 170)
        table.setColumnWidth(6, 180)
        table.setColumnWidth(7, 130)
        table.setColumnWidth(8, 110)
        table.setColumnWidth(9, 70)
        table.setColumnWidth(10, 260)
        table.setColumnWidth(11, 190)
        left_layout.addWidget(table, 1)

        scan_summary_label = QLabel("Scan to see package readiness summary.")
        scan_summary_label.setObjectName("HintLabel")
        scan_summary_label.setWordWrap(True)
        left_layout.addWidget(scan_summary_label)
        legend_label = QLabel(
            "Legend: Green=Yes (auto path-repair), Orange=No (manual review), "
            "Amber=No (build update needed or missing build metadata), "
            "Red=No (manual fixes / binary mismatch), "
            "Blue=No (already aligned), Gray=No payloads."
        )
        legend_label.setObjectName("HintLabel")
        legend_label.setWordWrap(True)
        left_layout.addWidget(legend_label)

        diff_label = QLabel("Update feasibility and plan for selected packages")
        diff_label.setObjectName("HintLabel")
        diff_label.setWordWrap(True)
        diff_preview = QTextBrowser()
        diff_preview.setReadOnly(True)
        diff_preview.setOpenExternalLinks(False)
        diff_preview.setMinimumWidth(360)
        diff_preview.setHtml(
            "<p>Select package rows and press <strong>Preview Update Plan</strong> or read this live preview below. "
            "The live preview uses path and size checks; Preview Update Plan runs exact byte compare for selected packages in update mode.</p>"
        )
        right_layout.addWidget(diff_label)
        right_layout.addWidget(diff_preview, 1)

        status_label = QLabel("Scan a source folder to find packaged mods.")
        status_label.setObjectName("HintLabel")
        left_layout.addWidget(status_label)

        selection_status_label = QLabel("Select package rows and check a box to see update summary.")
        selection_status_label.setObjectName("HintLabel")
        selection_status_label.setWordWrap(True)
        right_layout.addWidget(selection_status_label)
        content_splitter.setSizes([700, 420])

        def _apply_content_splitter_sizes() -> None:
            width = max(1, content_splitter.width())
            left_width = max(540, int(width * 0.56))
            right_width = max(420, width - left_width)
            if left_width + right_width > width:
                left_width = max(540, width - right_width)
            content_splitter.setSizes([left_width, right_width])

        QTimer.singleShot(0, _apply_content_splitter_sizes)
        QTimer.singleShot(120, _apply_content_splitter_sizes)

        button_row = QHBoxLayout()
        preview_button = QPushButton("Preview Update Plan")
        convert_button = QPushButton("Process Selected")
        open_output_button = QPushButton("Open Output Folder")
        button_row.addWidget(preview_button)
        button_row.addWidget(convert_button)
        button_row.addWidget(open_output_button)
        button_row.addStretch(1)
        if on_close is not None:
            close_button = QPushButton("Close")
            button_row.addWidget(close_button)
        else:
            close_button = None
        layout.addLayout(button_row)

        packages: List[RetrofittableModPackage] = []
        package_repair_summaries: List[RetrofitPathRepairSummary] = []
        profile_labels = dict(MOD_PACKAGE_MANAGER_PROFILE_LABELS)
        profile_labels["dmm"] = "Mod Manager"
        profile_labels["crimson_sharp"] = "Crimson Sharp / Crimson Browser"
        default_manager_profile = str(
            getattr(self.collect_config(), "mod_ready_manager_profile", "dmm") or "dmm"
        ).strip().lower()
        if default_manager_profile not in RETROFIT_MANAGER_PROFILES:
            default_manager_profile = "dmm"
        empty_repair_summary = RetrofitPathRepairSummary(mappings=tuple())
        _safe_output_name_suffixes: Dict[str, int] = {}

        def _set_table_cell_text(row: int, col: int, value: str) -> None:
            text = value or "-"
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            table.setItem(row, col, item)

        def _selected_package_rows() -> List[int]:
            rows: List[int] = []
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item is not None and item.checkState() == Qt.Checked:
                    rows.append(row)
            return rows

        def _summary_for_row(row: int) -> RetrofitPathRepairSummary:
            if 0 <= row < len(package_repair_summaries):
                return package_repair_summaries[row]
            return empty_repair_summary

        current_game_build_text = ""

        def _refresh_current_game_build_label() -> str:
            nonlocal current_game_build_text
            if not _is_update_mode():
                current_game_build_text = ""
                game_build_status_label.setText("Not used in Repackage only mode")
                game_build_status_label.setToolTip("Current game build is only used when update mode is selected.")
                return ""
            detected = _detect_current_game_build()
            current_game_build_text = detected
            if detected:
                game_build_status_label.setText(f"Detected game build: {detected}")
                game_build_status_label.setToolTip(f"Current game build: {detected}")
            else:
                game_build_status_label.setText("Detected game build: unknown")
                game_build_status_label.setToolTip(
                    "Set Game / Package path in Archive Browser and refresh index to detect the game build."
                )
            return detected

        def _readiness_for_summary(summary: RetrofitPathRepairSummary) -> tuple[str, str, str]:
            return retrofit_readiness_for_summary(summary, update_mode=_is_update_mode())

        def _readiness_label_for_summary(summary: RetrofitPathRepairSummary) -> str:
            return retrofit_readiness_label_for_summary(summary, update_mode=_is_update_mode())

        def _rebuild_repair_summaries() -> None:
            detected_build = _refresh_current_game_build_label()
            archive_index = self.archive_entries_by_basename if _is_update_mode() else None
            package_repair_summaries[:] = [
                build_retrofit_path_repair_summary(
                    package,
                    archive_entries_by_basename=archive_index,
                    current_game_build=detected_build,
                    compare_payload_bytes=False,
                )
                for package in packages
            ]

        def _build_update_plan_html(
            rows: Sequence[int],
            *,
            output_root: Optional[Path] = None,
            max_rows_per_package: int = 18,
            summary_by_row: Optional[Mapping[int, RetrofitPathRepairSummary]] = None,
        ) -> str:
            return build_retrofit_update_plan_html(
                rows,
                packages=packages,
                package_repair_summaries=package_repair_summaries,
                update_mode=_is_update_mode(),
                archive_index_size=len(getattr(self, "archive_entries_by_basename", {}) or {}),
                profiles_by_row={int(row): _manager_for_row(int(row)) for row in rows},
                profile_labels=profile_labels,
                output_root=output_root,
                max_rows_per_package=max_rows_per_package,
                summary_by_row=summary_by_row,
            )

        def _refresh_diff_preview() -> None:
            rows = _selected_package_rows()
            if not rows:
                diff_preview.setHtml("<p>No packages selected. Check package rows to inspect the selected operation plan.</p>")
                selection_status_label.setText("No packages selected.")
                return
            diff_preview.setHtml(_build_update_plan_html(rows, output_root=Path(output_edit.text().strip()).expanduser(), max_rows_per_package=12))
            selection_status_label.setText(_selection_readiness_summary(rows))

        def _apply_operation_mode_text() -> None:
            if _is_update_mode():
                mode_hint_label.setText(
                    "Update mode compares selected packages against the loaded current game files, repairs stale paths/new_paths where possible, then repackages."
                )
                legend_label.setText(
                    "Legend: Green=Yes (auto path-repair), Orange=No (manual review), "
                    "Amber=No (build update needed or missing build metadata), "
                    "Red=No (manual fixes / payload differs), "
                    "Blue=No (already aligned), Gray=No payloads."
                )
                diff_label.setText("Update feasibility and plan for selected packages")
                preview_button.setText("Preview Update Plan")
                refresh_index_button.setEnabled(True)
                header_item = table.horizontalHeaderItem(11)
                if header_item is not None:
                    header_item.setText("Update status")
                return
            mode_hint_label.setText(
                "Retrofitting mode does not inspect current game files or update stale paths. It only rewrites selected packages for another supported mod manager profile."
            )
            legend_label.setText(
                "Retrofitting only: no current-game update check is performed here. Use the GitHub update variant for game-version updates."
            )
            diff_label.setText("Retrofitting plan for selected packages")
            preview_button.setText("Preview Retrofit Plan")
            refresh_index_button.setEnabled(False)
            header_item = table.horizontalHeaderItem(11)
            if header_item is not None:
                header_item.setText("Operation status")

        def _refresh_archive_status() -> None:
            _apply_operation_mode_text()
            archive_index_status_label.setText(_build_archive_index_status_text())
            QTimer.singleShot(0, _hide_retrofit_clutter)
            if table.rowCount() > 0:
                _rebuild_repair_summaries()
                _populate_table()
            else:
                _refresh_current_game_build_label()
                selection_status_label.setText("No packages selected.")

        def _refresh_archive_index() -> None:
            self.scan_archives(force_refresh=True, activate_archive_tab=False)
            archive_index_status_label.setText("Refreshing game archive index...")
            QTimer.singleShot(1100, _refresh_archive_status)
            QTimer.singleShot(2600, _refresh_archive_status)
            QTimer.singleShot(4600, _refresh_archive_status)

        def _manager_for_row(row: int) -> str:
            combo = table.cellWidget(row, 5)
            if isinstance(combo, QComboBox):
                return str(combo.currentData() or "dmm")
            return "dmm"

        def _structure_for_row(row: int) -> str:
            combo = table.cellWidget(row, 6)
            if isinstance(combo, QComboBox):
                return str(combo.currentData() or "")
            return ""

        def _conflict_mode_for_row(row: int) -> str:
            combo = table.cellWidget(row, 7)
            if isinstance(combo, QComboBox):
                return str(combo.currentData() or "")
            return ""

        def _target_language_for_row(row: int) -> str:
            edit = table.cellWidget(row, 8)
            if isinstance(edit, QLineEdit):
                return edit.text().strip()
            return ""

        def _ready_zip_for_row(row: int) -> bool:
            checkbox = table.cellWidget(row, 9)
            if isinstance(checkbox, QCheckBox):
                return checkbox.isChecked()
            return True

        def _export_options_for_row(row: int) -> ModPackageExportOptions:
            profile = _manager_for_row(row)
            defaults = mod_package_export_options_for_manager(profile)
            structure = _structure_for_row(row) or defaults.structure
            uses_manager_metadata = mod_package_profile_uses_manager_metadata(profile)
            return ModPackageExportOptions(
                manager_targets=tuple(defaults.manager_targets),
                structure=structure,
                create_manifest_json=defaults.create_manifest_json,
                create_mod_json=defaults.create_mod_json,
                create_modinfo_json=defaults.create_modinfo_json,
                create_info_json=defaults.create_info_json,
                create_no_encrypt_file=defaults.create_no_encrypt_file,
                create_zip=_ready_zip_for_row(row),
                conflict_mode=_conflict_mode_for_row(row) if uses_manager_metadata else "",
                target_language=_target_language_for_row(row) if uses_manager_metadata else "",
                files_dir=defaults.files_dir,
            )

        def _apply_retrofit_profile_defaults(row: int) -> None:
            profile = _manager_for_row(row)
            defaults = mod_package_export_options_for_manager(profile)
            structure_combo = table.cellWidget(row, 6)
            if isinstance(structure_combo, QComboBox):
                index = structure_combo.findData(defaults.structure)
                if index >= 0:
                    structure_combo.setCurrentIndex(index)
                structure_combo.setEnabled(profile not in {"jmm", "field_json"})
            conflict_combo = table.cellWidget(row, 7)
            language_edit = table.cellWidget(row, 8)
            uses_manager_metadata = mod_package_profile_uses_manager_metadata(profile)
            if isinstance(conflict_combo, QComboBox):
                conflict_combo.setEnabled(uses_manager_metadata)
            if isinstance(language_edit, QLineEdit):
                language_edit.setEnabled(uses_manager_metadata)

        def _scan_readiness_summary() -> tuple[str, str]:
            return retrofit_scan_readiness_summary(
                package_count=len(packages),
                summaries=package_repair_summaries,
                update_mode=_is_update_mode(),
            )

        def _selection_readiness_summary(rows: Sequence[int]) -> str:
            return retrofit_selection_readiness_summary(
                rows,
                summaries=package_repair_summaries,
                update_mode=_is_update_mode(),
            )

        def _show_processing_results_dialog(
            processed: Sequence[tuple[str, Path, RetrofitPathRepairSummary]],
            failed: Sequence[tuple[str, str]],
        ) -> None:
            result_dialog = QDialog(message_parent)
            result_dialog.setWindowTitle(dialog_title)
            result_dialog.resize(880, 620)

            layout = QVBoxLayout(result_dialog)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(10)

            summary_html = build_retrofit_processing_results_html(
                processed,
                failed,
                update_mode=_is_update_mode(),
            )
            details_view = QTextBrowser()
            details_view.setReadOnly(True)
            details_view.setOpenExternalLinks(False)
            details_view.setHtml(summary_html)
            details_view.setMinimumHeight(430)
            layout.addWidget(details_view)
            button_row = QHBoxLayout()
            button_row.addStretch(1)
            close_button = QPushButton("Close")
            close_button.clicked.connect(result_dialog.accept)
            button_row.addWidget(close_button)
            layout.addLayout(button_row)
            result_dialog.exec()

        def _populate_table() -> None:
            table.setRowCount(0)
            if len(package_repair_summaries) != len(packages):
                _rebuild_repair_summaries()
            summary_title, summary_text = _scan_readiness_summary()
            scan_summary_label.setText(f"{summary_title}: {summary_text}")
            selection_status_label.setText(_selection_readiness_summary(_selected_package_rows()))
            for package in packages:
                row = table.rowCount()
                table.insertRow(row)
                use_item = QTableWidgetItem("")
                use_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                use_item.setCheckState(Qt.Checked)
                table.setItem(row, 0, use_item)
                _set_table_cell_text(row, 1, package.name)
                _set_table_cell_text(row, 2, package.kind)
                _set_table_cell_text(row, 3, ", ".join(package.existing_metadata))
                _set_table_cell_text(row, 4, str(len(package.payload_paths)))
                manager_combo = QComboBox()
                for profile in RETROFIT_MANAGER_PROFILES:
                    manager_combo.addItem(profile_labels.get(profile, profile), profile)
                default_index = manager_combo.findData(default_manager_profile)
                if default_index >= 0:
                    manager_combo.setCurrentIndex(default_index)
                manager_combo.setToolTip("Choose the manager profile to generate for this package.")
                table.setCellWidget(row, 5, manager_combo)
                structure_combo = QComboBox()
                structure_combo.addItem("Game-relative folders", "game_relative")
                structure_combo.addItem("files/ wrapper", "files_wrapper")
                structure_combo.addItem("Custom compact paths", "custom_compact_paths")
                structure_combo.addItem("DMM texture folder", "dmm_texture")
                structure_combo.addItem("Field-JSON v3.1 assets", "field_json_v31")
                table.setCellWidget(row, 6, structure_combo)
                conflict_combo = QComboBox()
                conflict_combo.addItem("Normal", "")
                conflict_combo.addItem("Override wins", "override")
                table.setCellWidget(row, 7, conflict_combo)
                language_edit = QLineEdit()
                language_edit.setPlaceholderText("Optional")
                table.setCellWidget(row, 8, language_edit)
                ready_zip_checkbox = QCheckBox()
                ready_zip_checkbox.setChecked(True)
                ready_zip_checkbox.setToolTip("Write rebuilt zip beside the converted folder.")
                table.setCellWidget(row, 9, ready_zip_checkbox)
                _set_table_cell_text(row, 10, "; ".join(package.warnings))
                feasibility_text = _readiness_label_for_summary(_summary_for_row(row))
                _, feasibility_detail, feasibility_color = _readiness_for_summary(_summary_for_row(row))
                feasibility_item = QTableWidgetItem(feasibility_text)
                feasibility_item.setToolTip(feasibility_detail)
                feasibility_item.setForeground(QBrush(QColor(feasibility_color)))
                table.setItem(row, 11, feasibility_item)
                manager_combo.currentIndexChanged.connect(lambda _index, table_row=row: _apply_retrofit_profile_defaults(table_row))
                _apply_retrofit_profile_defaults(row)
            status_message = f"Found {len(packages):,} packaged mod folder(s)."
            if _is_update_mode() and not getattr(self, "archive_entries_by_basename", {}):
                status_message += " No game archive index loaded."
            status_label.setText(status_message)
            _refresh_diff_preview()

        def _scan() -> None:
            source = Path(source_edit.text().strip()).expanduser()
            if not source.is_dir():
                QMessageBox.warning(message_parent, dialog_title, "Source folder does not exist.")
                return
            _safe_output_name_suffixes.clear()
            if not output_edit.text().strip():
                output_edit.setText(str(source / "converted"))
            packages[:] = collect_retrofittable_packages(source)
            _refresh_archive_status()
            _rebuild_repair_summaries()
            _populate_table()

        def _browse_source() -> None:
            selected_dir = QFileDialog.getExistingDirectory(message_parent, "Choose packaged mods folder", source_edit.text().strip())
            if selected_dir:
                source_edit.setText(selected_dir)
                output_edit.setText(str(Path(selected_dir).expanduser() / "converted"))

        def _browse_output() -> None:
            selected_dir = QFileDialog.getExistingDirectory(message_parent, "Choose converted output folder", output_edit.text().strip())
            if selected_dir:
                output_edit.setText(selected_dir)

        def _preview_plan() -> None:
            rows = _selected_package_rows()
            if not rows:
                QMessageBox.information(message_parent, dialog_title, "Select at least one package to preview.")
                return
            output_root = Path(output_edit.text().strip()).expanduser()
            preview_summaries: Dict[int, RetrofitPathRepairSummary] = {}
            if _is_update_mode():
                detected_build = _refresh_current_game_build_label()
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    for row in rows:
                        if 0 <= row < len(packages):
                            preview_summaries[row] = build_retrofit_path_repair_summary(
                                packages[row],
                                archive_entries_by_basename=self.archive_entries_by_basename,
                                current_game_build=detected_build,
                                compare_payload_bytes=True,
                            )
                finally:
                    QApplication.restoreOverrideCursor()
            diff_preview.setHtml(
                _build_update_plan_html(
                    rows,
                    output_root=output_root,
                    max_rows_per_package=28,
                    summary_by_row=preview_summaries,
                )
            )
            selection_status_label.setText(_selection_readiness_summary(rows))

        def _convert_selected() -> None:
            rows = _selected_package_rows()
            if not rows:
                QMessageBox.information(message_parent, dialog_title, "Select at least one package to process.")
                return
            if _is_update_mode() and not getattr(self, "archive_entries_by_basename", {}):
                QMessageBox.warning(
                    message_parent,
                    dialog_title,
                    "Update mode requires a loaded game archive index so the tool can compare against current game files.\n\n"
                    "Click Refresh Game Index first, or switch Operation to Repackage only.",
                )
                return
            risky_rows: List[int] = []
            if _is_update_mode():
                for row in rows:
                    summary = _summary_for_row(row)
                    if summary.unresolved_path_count or summary.ambiguous_path_count:
                        risky_rows.append(row)
            if risky_rows:
                risky_lines = [
                    "Some selected packages are not fully auto-fixable.",
                    "",
                ]
                for row in risky_rows[:6]:
                    summary = _summary_for_row(row)
                    package = packages[row]
                    risky_lines.append(
                        f"- {package.name}: unresolved={summary.unresolved_path_count}, ambiguous={summary.ambiguous_path_count}"
                    )
                if len(risky_rows) > 6:
                    risky_lines.append(f"- ... {len(risky_rows) - 6} more.")
                risky_lines.append("")
                risky_lines.append("Proceed with processing anyway?")
                if (
                    QMessageBox.question(
                        message_parent,
                        dialog_title,
                        "\n".join(risky_lines),
                        QMessageBox.Yes | QMessageBox.No,
                    )
                    != QMessageBox.Yes
                ):
                    return
            output_root = Path(output_edit.text().strip()).expanduser()
            processed: List[tuple[str, Path, RetrofitPathRepairSummary]] = []
            failed: List[tuple[str, str]] = []
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                for row in rows:
                    package = packages[row]
                    profile = _manager_for_row(row)
                    scan_summary = _summary_for_row(row)
                    archive_index_for_process = self.archive_entries_by_basename if _is_update_mode() else None
                    safe_name = next_available_retrofit_package_name(
                        package.name,
                        profile,
                        output_root,
                        _safe_output_name_suffixes,
                    )
                    converted_package = (
                        dataclasses.replace(package, name=safe_name)
                        if safe_name != package.name
                        else package
                    )
                    try:
                        result = retrofit_mod_package(
                            converted_package,
                            output_root,
                            manager_profile=profile,
                            export_options=_export_options_for_row(row),
                            archive_entries_by_basename=archive_index_for_process,
                        )
                        converted_output_name = (
                            f"{package.name}_{profile}" if safe_name == package.name else f"{safe_name}_{profile}"
                        )
                        processing_summary = dataclasses.replace(
                            scan_summary,
                            repaired_path_count=result.repaired_path_count,
                            unresolved_path_count=result.unresolved_path_count,
                            ambiguous_path_count=result.ambiguous_path_count,
                            warnings=result.warnings,
                        )
                        processed.append(
                            (
                                converted_output_name,
                                result.package_root,
                                processing_summary,
                            )
                        )
                    except Exception as exc:
                        failed.append((package.name, str(exc)))
            finally:
                QApplication.restoreOverrideCursor()
            status_label.setText(
                f"Processed {len(processed):,} package(s). Failed {len(failed):,} package(s)."
                if (processed or failed)
                else "No packages were selected for processing."
            )
            _show_processing_results_dialog(processed, failed)

        def _open_output() -> None:
            output_root = Path(output_edit.text().strip()).expanduser()
            output_root.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_root)))

        browse_source_button.clicked.connect(_browse_source)
        browse_output_button.clicked.connect(_browse_output)
        operation_combo.currentIndexChanged.connect(lambda _index: _refresh_archive_status())
        scan_button.clicked.connect(_scan)
        refresh_index_button.clicked.connect(_refresh_archive_index)
        preview_button.clicked.connect(_preview_plan)
        convert_button.clicked.connect(_convert_selected)
        open_output_button.clicked.connect(_open_output)
        if close_button is not None and on_close is not None:
            close_button.clicked.connect(on_close)
        table.itemSelectionChanged.connect(_refresh_diff_preview)
        table.itemChanged.connect(
            lambda item: _refresh_diff_preview()
            if isinstance(item, QTableWidgetItem) and item.column() == 0
            else None
        )

        _apply_operation_mode_text()
        _refresh_archive_status()
        if run_initial_scan:
            _scan()


__all__ = ["ArchiveModPackageRetrofitDialogMixin"]
