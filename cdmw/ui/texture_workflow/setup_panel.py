"""Texture workflow setup, backend, DDS guidance, and NCNN catalog helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.constants import (
    DEFAULT_UPSCALE_BACKEND,
    DDS_FORMAT_MODE_CUSTOM,
    DDS_MIP_MODE_CUSTOM,
    DDS_SIZE_MODE_CUSTOM,
    DDS_SIZE_MODE_ORIGINAL,
    DDS_SIZE_MODE_PNG,
    UPSCALE_BACKEND_CHAINNER,
    UPSCALE_BACKEND_NONE,
    UPSCALE_BACKEND_REALESRGAN_NCNN,
)
from cdmw.services.texture_workflow_service import (
    NCNN_CATALOG_SOURCE_LINKS,
    NCNN_MODEL_CATALOG,
    get_ncnn_catalog_entry,
)
from cdmw.services.texture_workflow_service import discover_realesrgan_ncnn_models, resolve_ncnn_model_dir
from cdmw.services.texture_workflow_service import get_texture_preset_definition
from cdmw.ui.safe_upscale_wizard import SafeUpscaleWizard
from cdmw.ui.shell.theme_controller import build_monospace_font


class TextureWorkflowSetupPanelMixin:
    """Texture workflow setup and backend UI helpers."""
    def _current_upscale_backend(self) -> str:
        if self.chainner_section.is_body_built():
            return self._combo_value(self.upscale_backend_combo)
        saved = str(self.settings.value("upscale/backend", DEFAULT_UPSCALE_BACKEND) or DEFAULT_UPSCALE_BACKEND)
        return saved if saved in {UPSCALE_BACKEND_NONE, UPSCALE_BACKEND_CHAINNER, UPSCALE_BACKEND_REALESRGAN_NCNN} else DEFAULT_UPSCALE_BACKEND

    def _sync_upscale_backend_stack_height(self) -> None:
        current_page = self.upscale_backend_stack.currentWidget()
        if current_page is None:
            self.upscale_backend_stack.setMinimumHeight(0)
            self.upscale_backend_stack.setMaximumHeight(16777215)
            return
        target_height = max(0, current_page.sizeHint().height())
        self.upscale_backend_stack.setMinimumHeight(target_height)
        self.upscale_backend_stack.setMaximumHeight(target_height)

    def _apply_upscale_backend_state(self) -> None:
        if not self.chainner_section.is_body_built():
            return
        backend = self._current_upscale_backend()
        if backend == UPSCALE_BACKEND_CHAINNER:
            self.upscale_backend_stack.setCurrentIndex(1)
        elif backend == UPSCALE_BACKEND_REALESRGAN_NCNN:
            self.upscale_backend_stack.setCurrentIndex(2)
        else:
            self.upscale_backend_stack.setCurrentIndex(0)

        chainner_enabled = backend == UPSCALE_BACKEND_CHAINNER
        self.chainner_exe_path_edit.setEnabled(chainner_enabled)
        self.chainner_chain_path_edit.setEnabled(chainner_enabled)
        self.chainner_override_edit.setEnabled(chainner_enabled)
        self.chainner_exe_browse_button.setEnabled(chainner_enabled)
        self.chainner_chain_browse_button.setEnabled(chainner_enabled)
        self.validate_chainner_button.setEnabled(chainner_enabled)

        ncnn_enabled = backend == UPSCALE_BACKEND_REALESRGAN_NCNN
        self.ncnn_exe_path_edit.setEnabled(ncnn_enabled)
        self.ncnn_model_dir_edit.setEnabled(ncnn_enabled)
        self.ncnn_exe_browse_button.setEnabled(ncnn_enabled)
        self.ncnn_model_dir_browse_button.setEnabled(ncnn_enabled)
        self.ncnn_model_combo.setEnabled(ncnn_enabled and self.ncnn_model_combo.count() > 0 and bool(self._combo_value(self.ncnn_model_combo)))
        self.ncnn_model_refresh_button.setEnabled(ncnn_enabled)
        self.ncnn_extra_args_edit.setEnabled(ncnn_enabled)
        direct_backend_enabled = backend == UPSCALE_BACKEND_REALESRGAN_NCNN
        self.texture_policy_group.setVisible(True)
        self.direct_backend_controls_group.setVisible(direct_backend_enabled)
        self.ncnn_scale_spin.setEnabled(direct_backend_enabled)
        self.ncnn_tile_size_spin.setEnabled(direct_backend_enabled)
        self.upscale_post_correction_combo.setEnabled(direct_backend_enabled)
        self.upscale_texture_preset_combo.setEnabled(True)
        self.enable_automatic_texture_rules_checkbox.setEnabled(True)
        self.retry_smaller_tile_checkbox.setEnabled(direct_backend_enabled)
        self.enable_mod_ready_loose_export_checkbox.setEnabled(True)
        self.mod_ready_export_root_edit.setEnabled(self.enable_mod_ready_loose_export_checkbox.isChecked())
        self.mod_ready_export_browse_button.setEnabled(self.enable_mod_ready_loose_export_checkbox.isChecked())
        self.mod_ready_package_group.setVisible(self.enable_mod_ready_loose_export_checkbox.isChecked())
        if self.filters_section.is_body_built():
            self._refresh_workflow_profile_ncnn_model_combo()
            self._sync_workflow_editor_state()
        self._update_ncnn_preset_hint()
        if self.dds_output_section.is_body_built():
            self._refresh_dds_output_hints()
        self._sync_upscale_backend_stack_height()

    def _build_ncnn_model_picker_page(self) -> QWidget:
        ncnn_page = QWidget()
        ncnn_page.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        ncnn_layout = QVBoxLayout(ncnn_page)
        ncnn_layout.setContentsMargins(0, 0, 0, 0)
        ncnn_layout.setSpacing(8)

        ncnn_paths_layout = QGridLayout()
        ncnn_paths_layout.setHorizontalSpacing(10)
        ncnn_paths_layout.setVerticalSpacing(10)
        ncnn_paths_layout.setColumnMinimumWidth(0, 136)
        ncnn_paths_layout.setColumnStretch(1, 1)
        self.ncnn_exe_path_edit = QLineEdit()
        self.ncnn_model_dir_edit = QLineEdit()
        self.ncnn_exe_browse_button = self._add_path_row(
            ncnn_paths_layout,
            0,
            "NCNN exe path",
            self.ncnn_exe_path_edit,
            self._browse_ncnn_exe_path,
        )
        self.ncnn_model_dir_browse_button = self._add_path_row(
            ncnn_paths_layout,
            1,
            "Model folder",
            self.ncnn_model_dir_edit,
            self._browse_ncnn_model_dir,
        )
        ncnn_layout.addLayout(ncnn_paths_layout)

        ncnn_options_layout = QGridLayout()
        ncnn_options_layout.setHorizontalSpacing(10)
        ncnn_options_layout.setVerticalSpacing(8)
        ncnn_options_layout.setColumnMinimumWidth(0, 136)
        ncnn_options_layout.setColumnStretch(1, 1)

        self.ncnn_model_combo = QComboBox()
        self.ncnn_model_refresh_button = QPushButton("Refresh Models")
        self.ncnn_model_catalog_button = QPushButton("Catalog")
        self.ncnn_model_catalog_button.setToolTip(
            "Browse grouped NCNN model recommendations with short descriptions, source pages, and non-downloading model pages."
        )
        model_row = QHBoxLayout()
        model_row.setContentsMargins(0, 0, 0, 0)
        model_row.setSpacing(8)
        model_row.addWidget(self.ncnn_model_combo, stretch=1)
        model_row.addWidget(self.ncnn_model_refresh_button)
        model_row.addWidget(self.ncnn_model_catalog_button)

        ncnn_options_layout.addWidget(QLabel("Model"), 0, 0)
        ncnn_options_layout.addLayout(model_row, 0, 1)
        ncnn_layout.addLayout(ncnn_options_layout)
        return ncnn_page

    def _create_guidance_panel(self, rows: Sequence[Tuple[str, str]]):
        panel = QFrame()
        panel.setObjectName("GuidancePanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)
        row_widgets = {}
        for role, title in rows:
            row_frame = QFrame()
            row_frame.setObjectName("GuidanceRow")
            row_frame.setProperty("guidanceRole", role)
            row_layout = QHBoxLayout(row_frame)
            row_layout.setContentsMargins(6, 4, 6, 4)
            row_layout.setSpacing(8)

            chip = QLabel()
            chip.setObjectName("GuidanceChip")
            chip.setProperty("guidanceRole", role)
            chip.setFixedSize(10, 10)

            title_label = QLabel(title)
            title_label.setObjectName("GuidanceTitle")
            title_label.setMinimumWidth(150)

            value_label = QLabel()
            value_label.setObjectName("GuidanceValue")
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

            row_layout.addWidget(chip, 0, Qt.AlignTop)
            row_layout.addWidget(title_label, 0, Qt.AlignTop)
            row_layout.addWidget(value_label, 1)
            layout.addWidget(row_frame)
            row_widgets[role] = (row_frame, title_label, value_label)
        return panel, row_widgets

    def _set_guidance_rows(
        self,
        row_widgets: Dict[str, Tuple[QFrame, QLabel, QLabel]],
        entries: Sequence[Tuple[str, str, str]],
    ) -> None:
        used_roles = set()
        for role, title, value in entries:
            row_frame, title_label, value_label = row_widgets[role]
            title_label.setText(title)
            value_label.setText(value)
            row_frame.setVisible(True)
            used_roles.add(role)
        for role, (row_frame, _title_label, _value_label) in row_widgets.items():
            if role not in used_roles:
                row_frame.setVisible(False)

    def _create_dds_output_flow_row(self, role: str, title: str):
        row = QFrame()
        row.setObjectName("DdsFlowRow")
        row.setProperty("flowRole", role)
        layout = QVBoxLayout(row)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(5)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)

        chip = QLabel()
        chip.setObjectName("DdsFlowChip")
        chip.setProperty("flowRole", role)
        chip.setFixedSize(10, 10)

        title_label = QLabel(title)
        title_label.setObjectName("DdsFlowTitle")

        value_label = QLabel()
        value_label.setObjectName("DdsFlowValue")
        value_label.setWordWrap(False)
        value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        value_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        title_row.addWidget(chip, 0, Qt.AlignVCenter)
        title_row.addWidget(title_label, 1)
        layout.addLayout(title_row)
        layout.addWidget(value_label)
        return row, title_label, value_label

    def _set_dds_output_flow(self, entries: Sequence[Tuple[str, str, str]]) -> None:
        used_roles = set()
        for role, title, value in entries:
            row_frame, title_label, value_label = self.dds_output_flow_rows[role]
            title_label.setText(title)
            value_label.setText(value)
            row_frame.setVisible(True)
            used_roles.add(role)
        for role, (row_frame, _title_label, _value_label) in self.dds_output_flow_rows.items():
            if role not in used_roles:
                row_frame.setVisible(False)

    def _apply_dds_staging_enabled_state(self) -> None:
        if not self.dds_output_section.is_body_built():
            return
        enabled = self.enable_dds_staging_checkbox.isChecked()
        self.dds_staging_root_edit.setEnabled(enabled)
        self.dds_staging_browse_button.setEnabled(enabled)
        self._apply_upscale_backend_state()

    def _apply_dds_output_state(self) -> None:
        if not self.dds_output_section.is_body_built():
            return
        format_is_custom = self._combo_value(self.dds_format_mode_combo) == DDS_FORMAT_MODE_CUSTOM
        size_is_custom = self._combo_value(self.dds_size_mode_combo) == DDS_SIZE_MODE_CUSTOM
        mip_is_custom = self._combo_value(self.dds_mip_mode_combo) == DDS_MIP_MODE_CUSTOM
        self.dds_custom_format_label.setVisible(format_is_custom)
        self.dds_custom_format_combo.setVisible(format_is_custom)
        self.dds_custom_size_label.setVisible(size_is_custom)
        self.dds_custom_size_widget.setVisible(size_is_custom)
        self.dds_custom_mip_label.setVisible(mip_is_custom)
        self.dds_custom_mip_spin.setVisible(mip_is_custom)
        self._refresh_dds_output_hints()

    def _refresh_dds_output_hints(self) -> None:
        backend = self._current_upscale_backend()
        staging_enabled = self.enable_dds_staging_checkbox.isChecked()
        staging_root_text = self.dds_staging_root_edit.text().strip() or "(staging PNG root)"
        png_root_text = self.png_root_edit.text().strip() or "(PNG root)"
        output_root_text = self.output_root_edit.text().strip() or "(output root)"

        if staging_enabled:
            if backend == UPSCALE_BACKEND_CHAINNER:
                self.dds_output_mode_hint.setText(
                    "DDS files are converted to source PNGs first. PNG-input chaiNNer chains should read the staging PNG root. DDS-direct chains can ignore the staged PNGs if the chain already reads DDS."
                )
                self._set_dds_output_flow(
                    [
                        ("source", "Source PNG folder", staging_root_text),
                        ("final", "Final PNG after chaiNNer", png_root_text),
                        ("dds", "Rebuilt DDS folder", output_root_text),
                    ]
                )
            elif backend == UPSCALE_BACKEND_REALESRGAN_NCNN:
                self.dds_output_mode_hint.setText(
                    "DDS files are converted to source PNGs first. Real-ESRGAN NCNN reads the staged PNGs and writes the final upscaled PNGs into PNG root."
                )
                self._set_dds_output_flow(
                    [
                        ("source", "Source PNG folder", staging_root_text),
                        ("final", "Final upscaled PNG folder", png_root_text),
                        ("dds", "Rebuilt DDS folder", output_root_text),
                    ]
                )
            else:
                self.dds_output_mode_hint.setText(
                    "DDS files are converted to PNG first. With no backend selected, Start stops after PNG conversion and does not rebuild DDS."
                )
                self._set_dds_output_flow(
                    [
                        ("source", "Converted PNG folder", png_root_text),
                        ("note", "Status", "No DDS rebuild happens in this mode."),
                    ]
                )
        else:
            if backend == UPSCALE_BACKEND_CHAINNER:
                self.dds_output_mode_hint.setText(
                    "chaiNNer is enabled without DDS staging. PNG-input chains must read from the existing PNG root or another path defined by the chain. DDS-direct chains can still read DDS directly if the chain supports it."
                )
                self._set_dds_output_flow(
                    [
                        ("source", "PNG input for chains", png_root_text),
                        ("final", "Final PNG after chaiNNer", png_root_text),
                        ("dds", "Rebuilt DDS folder", output_root_text),
                    ]
                )
            elif backend == UPSCALE_BACKEND_REALESRGAN_NCNN:
                self.dds_output_mode_hint.setText(
                    "Real-ESRGAN NCNN is enabled without DDS staging, so it upscales the existing PNG root before DDS rebuild."
                )
                self._set_dds_output_flow(
                    [
                        ("source", "Source and final PNG folder", png_root_text),
                        ("dds", "Rebuilt DDS folder", output_root_text),
                    ]
                )
            else:
                self.dds_output_mode_hint.setText("DDS rebuild uses the existing PNG root directly.")
                self._set_dds_output_flow(
                    [
                        ("source", "Existing PNG folder", png_root_text),
                        ("dds", "Rebuilt DDS folder", output_root_text),
                    ]
                )

        size_mode = self._combo_value(self.dds_size_mode_combo)
        if size_mode == DDS_SIZE_MODE_PNG:
            self.dds_output_size_hint.setText(
                "Size mode: the rebuilt DDS uses the final PNG dimensions from PNG root. This changes DDS size only. It does not decide where PNG files are written."
            )
        elif size_mode == DDS_SIZE_MODE_ORIGINAL:
            self.dds_output_size_hint.setText(
                "Size mode: the rebuilt DDS keeps the original DDS width and height, even if the PNG files in PNG root are larger or smaller."
            )
        else:
            self.dds_output_size_hint.setText(
                "Size mode: the rebuilt DDS uses the custom width and height below. This does not change where PNG files are written."
            )

    def _update_ncnn_preset_hint(self) -> None:
        if not self.chainner_section.is_body_built():
            return
        tr = self.ui_localizer.translate
        preset_definition = get_texture_preset_definition(self._combo_value(self.upscale_texture_preset_combo))
        upscale_list = ", ".join(preset_definition.upscale_types)
        copy_list = ", ".join(preset_definition.copy_types) if preset_definition.copy_types else tr("nothing")
        rules_text = (
            tr("On: final color space, compression, alpha-aware hints, and technical-map preservation are still checked after the preset is applied.")
            if self.enable_automatic_texture_rules_checkbox.isChecked()
            else tr("Off: the preset still chooses which texture types enter the PNG/upscale path, but automatic DDS safety recommendations are disabled.")
        )
        policy_entries = [
            ("summary", tr("Preset summary"), tr(preset_definition.description)),
            ("upscaled", tr("Upscaled"), upscale_list),
            ("copied", tr("Copied unchanged"), copy_list),
            (
                "rules",
                tr("Safety rules"),
                rules_text,
            ),
        ]
        if self.enable_unsafe_technical_override_checkbox.isChecked():
            policy_entries.append(
                (
                    "override",
                    tr("Expert override"),
                    tr("Enabled: technical textures can be forced through the generic visible-color PNG/upscale path even when the planner would normally preserve them."),
                )
            )
        if preset_definition.warning:
            policy_entries.append(("warning", tr("Warning"), tr(preset_definition.warning)))
        self._set_guidance_rows(self.texture_policy_hint_rows, policy_entries)

        backend = self._current_upscale_backend()
        if backend == UPSCALE_BACKEND_CHAINNER:
            self.direct_backend_controls_group.setToolTip("")
        elif backend == UPSCALE_BACKEND_REALESRGAN_NCNN:
            self.direct_backend_controls_group.setToolTip("")
        else:
            self.direct_backend_controls_group.setToolTip("")

    def open_run_summary(self) -> None:
        dialog = SafeUpscaleWizard(theme_key=self.current_theme_key, parent=self)
        config = self.collect_config()
        dialog.populate_from_config(
            {
                "upscale_backend": config.upscale_backend,
                "preset": config.upscale_texture_preset,
                "scale": config.ncnn_scale,
                "tile_size": config.ncnn_tile_size,
                "ncnn_extra_args": config.ncnn_extra_args,
                "post_correction_mode": config.upscale_post_correction_mode,
                "use_automatic_rules": config.enable_automatic_texture_rules,
                "unsafe_technical_override": config.enable_unsafe_technical_override,
                "retry_smaller_tile": config.retry_smaller_tile_on_failure,
                "loose_export": config.enable_mod_ready_loose_export,
                "source_root": config.archive_package_root or config.original_dds_root,
                "archive_root": config.archive_package_root,
                "original_dds_root": config.original_dds_root,
                "png_root": config.png_root,
                "output_root": config.output_root,
                "staging_png_root": config.dds_staging_root,
                "notes": "This dialog is read-only. Model paths and all editable backend or texture-policy controls remain in the main Texture Workflow panel.",
            }
        )
        dialog.exec()

    def _open_external_urls(self, urls: Sequence[str], *, label: str) -> None:
        unique_urls: List[str] = []
        seen: set[str] = set()
        for raw_url in urls:
            url = str(raw_url or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            unique_urls.append(url)

        if not unique_urls:
            self.set_status_message(f"No external URL is available for {label}.", error=True)
            return

        opened = 0
        for url in unique_urls:
            if QDesktopServices.openUrl(QUrl(url)):
                opened += 1
                self.append_log(f"{label}: {url}")
            else:
                self.append_log(f"Could not open external URL for {label}: {url}")

        if opened == len(unique_urls):
            noun = "URL" if opened == 1 else "URLs"
            self.set_status_message(f"Opened {opened} external {noun} for {label}.")
            return
        if opened > 0:
            self.set_status_message(f"Opened some external URLs for {label}. Check the log for details.", error=True)
            return
        self.set_status_message(f"Could not open any external URLs for {label}.", error=True)

    def _format_ncnn_catalog_details(self, entry) -> str:
        file_list = "\n".join(f"- {name}" for name in sorted(entry.model_files))
        download_urls = "\n".join(f"- {name}: {url}" for name, url in sorted(entry.model_files.items()))
        return (
            f"Model: {entry.model_name}\n"
            f"Native scale: {entry.native_scale}x\n"
            f"Category: {entry.usage_group}\n"
            f"Best for: {entry.content_type}\n"
            f"Short description: {entry.short_description}\n"
            f"Source: {entry.source_name}\n"
            f"Source page: {entry.source_page_url}\n\n"
            f"Required files:\n{file_list}\n\n"
            f"Model pages:\n{download_urls}\n\n"
            f"Texture guidance: treat these built-in NCNN recommendations as visible color/albedo/UI texture models. "
            f"Do not assume they are safe for normal maps, masks, height, displacement, or other technical DDS data."
        )

    def _format_local_ncnn_model_details(self, model_name: str, model_dir: Path) -> str:
        stem = model_name.strip()
        return (
            f"Detected local model: {stem}\n"
            f"Model folder: {model_dir}\n\n"
            f"Expected files:\n"
            f"- {stem}.param\n"
            f"- {stem}.bin\n\n"
            f"This model was found in the configured NCNN model folder, not in the built-in catalog.\n"
            f"Manual imports are fully supported, but the app does not know this model's intended content type, "
            f"preferred scale, or whether it is safe for normals, masks, or other technical textures."
        )

    def _open_ncnn_catalog_entry_urls(self, entry) -> None:
        self._open_external_urls(
            [url for _file_name, url in sorted(entry.model_files.items())],
            label=f"NCNN model '{entry.model_name}'",
        )

    def open_ncnn_model_catalog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("NCNN Model Catalog")
        dialog.resize(780, 540)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        intro = QLabel(
            "Browse NCNN model categories on the left, then expand a category to review its recommended models. "
            "Built-in entries include source links, non-downloading model pages, and purpose notes so users do not assume every model is interchangeable."
        )
        intro.setWordWrap(True)
        intro.setObjectName("HintLabel")
        layout.addWidget(intro)

        safety_hint = QLabel(
            "Technical DDS maps such as normals, packed masks, height, displacement, bump, and other precision-sensitive textures "
            "do not currently have built-in NCNN model recommendations here. Keep relying on Texture Policy to preserve those safely."
        )
        safety_hint.setWordWrap(True)
        safety_hint.setObjectName("HintLabel")
        layout.addWidget(safety_hint)

        sources_label = QLabel(
            "Popular sources: "
            + " | ".join(
                f'<a href="{url}">{label}</a>' for label, url in NCNN_CATALOG_SOURCE_LINKS
            )
        )
        sources_label.setOpenExternalLinks(True)
        sources_label.setObjectName("HintLabel")
        sources_label.setWordWrap(True)
        layout.addWidget(sources_label)

        content_row = QHBoxLayout()
        content_row.setSpacing(10)
        layout.addLayout(content_row, 1)

        catalog_tree = QTreeWidget()
        catalog_tree.setHeaderHidden(True)
        catalog_tree.setRootIsDecorated(True)
        catalog_tree.setUniformRowHeights(True)
        catalog_tree.setIndentation(18)
        catalog_tree.setMinimumWidth(280)
        details_view = QPlainTextEdit()
        details_view.setReadOnly(True)
        details_view.setMinimumWidth(340)
        details_font = build_monospace_font(self.settings)
        details_view.setFont(details_font)
        details_view.document().setDefaultFont(details_font)
        content_row.addWidget(catalog_tree, stretch=1)
        content_row.addWidget(details_view, stretch=2)

        curated_names = {entry.model_name for entry in NCNN_MODEL_CATALOG}
        grouped_catalog: Dict[str, list] = {}
        for entry in NCNN_MODEL_CATALOG:
            grouped_catalog.setdefault(entry.usage_group, []).append(entry)

        first_model_item: Optional[QTreeWidgetItem] = None
        for group_name, group_entries in grouped_catalog.items():
            group_item = QTreeWidgetItem([f"{group_name} ({len(group_entries)} models)"])
            group_item.setData(
                0,
                Qt.UserRole,
                {"kind": "group", "group_name": group_name, "count": len(group_entries)},
            )
            group_item.setToolTip(0, f"Expand to view {len(group_entries)} recommended models.")
            group_font = group_item.font(0)
            group_font.setBold(True)
            group_item.setFont(0, group_font)
            catalog_tree.addTopLevelItem(group_item)
            for entry in group_entries:
                item = QTreeWidgetItem(group_item, [f"{entry.model_name} ({entry.native_scale}x)"])
                item.setData(0, Qt.UserRole, {"kind": "catalog", "model_name": entry.model_name})
                item.setToolTip(0, f"{entry.content_type}: {entry.short_description}")
                if first_model_item is None:
                    first_model_item = item

        exe_text = self.ncnn_exe_path_edit.text().strip()
        model_dir_text = self.ncnn_model_dir_edit.text().strip()
        exe_path = Path(exe_text).expanduser() if exe_text else None
        if exe_path is not None and not exe_path.exists():
            exe_path = None
        explicit_model_dir = Path(model_dir_text).expanduser() if model_dir_text else None
        if explicit_model_dir is not None and not explicit_model_dir.exists():
            explicit_model_dir = None
        detected_local_models = [
            (model_name, model_dir)
            for model_name, model_dir in discover_realesrgan_ncnn_models(exe_path, explicit_model_dir)
            if model_name not in curated_names
        ]
        if detected_local_models:
            local_group = QTreeWidgetItem([f"Detected local models ({len(detected_local_models)})"])
            local_group.setData(
                0,
                Qt.UserRole,
                {
                    "kind": "group",
                    "group_name": "Detected local models",
                    "count": len(detected_local_models),
                },
            )
            local_group.setToolTip(0, "Expand to view additional models found in your configured NCNN model folder.")
            local_group_font = local_group.font(0)
            local_group_font.setBold(True)
            local_group.setFont(0, local_group_font)
            catalog_tree.addTopLevelItem(local_group)
            for model_name, model_dir in detected_local_models:
                item = QTreeWidgetItem(local_group, [f"{model_name} (Local)"])
                item.setData(
                    0,
                    Qt.UserRole,
                    {"kind": "local", "model_name": model_name, "model_dir": str(model_dir)},
                )
                item.setToolTip(0, f"Detected from {model_dir}")
                if first_model_item is None:
                    first_model_item = item

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        open_source_button = QPushButton("Open Source")
        use_selected_button = QPushButton("Use Selected")
        open_download_urls_button = QPushButton("Open Model Pages")
        close_button = QPushButton("Close")
        button_row.addWidget(open_source_button)
        button_row.addWidget(use_selected_button)
        button_row.addStretch(1)
        button_row.addWidget(open_download_urls_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        def current_item_data() -> Optional[dict]:
            item = catalog_tree.currentItem()
            if item is None:
                return None
            data = item.data(0, Qt.UserRole)
            return data if isinstance(data, dict) else None

        def current_entry():
            item_data = current_item_data()
            if not item_data or item_data.get("kind") != "catalog":
                return None
            return get_ncnn_catalog_entry(str(item_data.get("model_name") or ""))

        def update_details() -> None:
            item_data = current_item_data()
            entry = current_entry()
            if item_data is None:
                details_view.setPlainText(
                    "Expand a category on the left, then select a built-in or detected local NCNN model to review it."
                )
                open_source_button.setEnabled(False)
                use_selected_button.setEnabled(False)
                open_download_urls_button.setEnabled(False)
                return
            if item_data.get("kind") == "group":
                group_name = str(item_data.get("group_name") or "Category")
                count = int(item_data.get("count") or 0)
                details_view.setPlainText(
                    f"Category: {group_name}\n"
                    f"Models: {count}\n\n"
                    "Expand this category and select a model to review its purpose, source, and non-downloading model pages."
                )
                open_source_button.setEnabled(False)
                use_selected_button.setEnabled(False)
                open_download_urls_button.setEnabled(False)
                return
            if item_data.get("kind") == "catalog" and entry is not None:
                details_view.setPlainText(self._format_ncnn_catalog_details(entry))
                open_source_button.setEnabled(True)
                use_selected_button.setEnabled(True)
                open_download_urls_button.setEnabled(True)
                return
            model_name = str(item_data.get("model_name") or "")
            model_dir = Path(str(item_data.get("model_dir") or ""))
            details_view.setPlainText(self._format_local_ncnn_model_details(model_name, model_dir))
            open_source_button.setEnabled(False)
            use_selected_button.setEnabled(bool(model_name))
            open_download_urls_button.setEnabled(False)

        def open_source() -> None:
            entry = current_entry()
            if entry is None:
                return
            QDesktopServices.openUrl(QUrl(entry.source_page_url))

        def use_selected() -> None:
            item_data = current_item_data()
            if item_data is None:
                return
            model_name = str(item_data.get("model_name") or "")
            if not model_name:
                return
            preferred_scale = 4
            entry = get_ncnn_catalog_entry(model_name)
            if entry is not None:
                preferred_scale = entry.native_scale
            self._refresh_ncnn_model_picker(preferred_name=model_name)
            self.ncnn_scale_spin.setValue(
                max(self.ncnn_scale_spin.minimum(), min(self.ncnn_scale_spin.maximum(), int(preferred_scale)))
            )
            dialog.accept()

        def open_download_urls() -> None:
            entry = current_entry()
            if entry is None:
                return
            self._open_ncnn_catalog_entry_urls(entry)

        def handle_tree_item_activated(item: QTreeWidgetItem, _column: int) -> None:
            item_data = item.data(0, Qt.UserRole)
            if not isinstance(item_data, dict):
                return
            if item_data.get("kind") == "group":
                item.setExpanded(not item.isExpanded())
                return
            use_selected()

        catalog_tree.currentItemChanged.connect(lambda *_args: update_details())
        catalog_tree.itemActivated.connect(handle_tree_item_activated)
        open_source_button.clicked.connect(open_source)
        use_selected_button.clicked.connect(use_selected)
        open_download_urls_button.clicked.connect(open_download_urls)
        close_button.clicked.connect(dialog.reject)

        if catalog_tree.topLevelItemCount() > 0:
            for index in range(catalog_tree.topLevelItemCount()):
                group_item = catalog_tree.topLevelItem(index)
                group_item.setExpanded(index == 0)
            if first_model_item is not None:
                catalog_tree.setCurrentItem(first_model_item)
            else:
                catalog_tree.setCurrentItem(catalog_tree.topLevelItem(0))
        else:
            update_details()

        dialog.exec()

    def _refresh_ncnn_model_picker(self, *_args, preferred_name: str = "") -> None:
        current_value = preferred_name or self._combo_value(self.ncnn_model_combo)
        exe_text = self.ncnn_exe_path_edit.text().strip()
        model_dir_text = self.ncnn_model_dir_edit.text().strip()

        exe_path = Path(exe_text).expanduser() if exe_text else None
        if exe_path is not None and not exe_path.exists():
            exe_path = None
        explicit_model_dir = Path(model_dir_text).expanduser() if model_dir_text else None
        if explicit_model_dir is not None and not explicit_model_dir.exists():
            explicit_model_dir = None

        resolved_model_dir = resolve_ncnn_model_dir(exe_path, explicit_model_dir)
        if not model_dir_text and resolved_model_dir is not None and resolved_model_dir.exists():
            self.ncnn_model_dir_edit.blockSignals(True)
            self.ncnn_model_dir_edit.setText(str(resolved_model_dir))
            self.ncnn_model_dir_edit.blockSignals(False)

        discovered_models = discover_realesrgan_ncnn_models(exe_path, resolved_model_dir)
        self.ncnn_model_combo.blockSignals(True)
        self.ncnn_model_combo.clear()
        for model_name, _model_dir in discovered_models:
            self._add_combo_choice(self.ncnn_model_combo, model_name, model_name)
        if not discovered_models:
            self._add_combo_choice(self.ncnn_model_combo, "No models detected", "")
        target_name = current_value or (discovered_models[0][0] if discovered_models else "")
        self._set_combo_by_value(self.ncnn_model_combo, target_name)
        self.ncnn_model_combo.blockSignals(False)
        self._apply_upscale_backend_state()

__all__ = ["TextureWorkflowSetupPanelMixin"]
