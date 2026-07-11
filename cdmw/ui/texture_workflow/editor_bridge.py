"""Texture editor bridge helpers for texture workflow shell actions."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Optional

from PySide6.QtWidgets import QAbstractItemView, QFileDialog, QLineEdit, QMessageBox

from cdmw.constants import APP_TITLE, ARCHIVE_MIN_SIZE_KB, ARCHIVE_ROLE_FILTER, ARCHIVE_STRUCTURE_FILTER
from cdmw.services.archive_preview_service import ensure_archive_preview_source
from cdmw.services.texture_workflow_service import common_workspace_root_from_config, suggested_workspace_paths
from cdmw.services.workspace_layout import app_root_from_workspace_member
from cdmw.models import ArchiveEntry, TextureEditorSourceBinding, TextureEditorToolSettings


class TextureWorkflowEditorBridgeMixin:
    """Coordinate Texture Editor launch and archive/workflow target binding."""
    def _build_texture_editor_binding_for_loose_path(
        self,
        source_path: Path,
        *,
        launch_origin: str,
        original_dds_path: Optional[Path] = None,
    ) -> TextureEditorSourceBinding:
        resolved = source_path.expanduser().resolve()
        relative_path = ""
        package_root = ""
        archive_relative_path = ""
        original_root_text = self.original_dds_edit.text().strip()
        png_root_text = self.png_root_edit.text().strip()
        texture_editor_png_root_text = self.texture_editor_png_root_edit.text().strip()
        original_root = Path(original_root_text).expanduser().resolve() if original_root_text else None
        png_root = Path(png_root_text).expanduser().resolve() if png_root_text else None
        texture_editor_png_root = (
            Path(texture_editor_png_root_text).expanduser().resolve()
            if texture_editor_png_root_text
            else None
        )

        for root in (original_root, png_root, texture_editor_png_root):
            if root is None:
                continue
            try:
                relative = resolved.relative_to(root)
            except Exception:
                continue
            relative_path = PurePosixPath(relative.as_posix()).as_posix()
            parts = [part for part in PurePosixPath(relative_path).parts if part]
            if parts:
                package_root = parts[0]
                archive_relative_path = PurePosixPath(*parts[1:]).as_posix() if len(parts) > 1 else parts[0]
            break

        chosen_original = original_dds_path
        if chosen_original is None and resolved.suffix.lower() == ".dds":
            chosen_original = resolved
        if chosen_original is None and original_root is not None and relative_path:
            candidate = (original_root / Path(PurePosixPath(relative_path))).with_suffix(".dds")
            if candidate.exists():
                chosen_original = candidate

        return TextureEditorSourceBinding(
            launch_origin=launch_origin,
            display_name=resolved.name,
            source_path=str(resolved),
            relative_path=relative_path,
            package_root=package_root,
            archive_relative_path=archive_relative_path,
            original_dds_path=str(chosen_original) if chosen_original is not None else "",
        )

    def _suggest_workflow_root_path(self, key: str) -> Optional[Path]:
        try:
            common = common_workspace_root_from_config(self.collect_config())
        except Exception:
            common = None
        if common is not None:
            suggested = suggested_workspace_paths(common).get(key)
            if suggested is not None:
                return suggested

        known_root_names = {
            "input_dds",
            "png_upscaled",
            "png_texture_editor",
            "png_staged_input",
            "dds_final",
            "archive_extract",
            "dds_final_mod_ready_loose_export",
            "mod_ready_loose_export",
        }
        for text in (
            self.original_dds_edit.text().strip(),
            self.png_root_edit.text().strip(),
            self.texture_editor_png_root_edit.text().strip(),
            self.dds_staging_root_edit.text().strip(),
            self.output_root_edit.text().strip(),
            self.archive_extract_root_edit.text().strip(),
        ):
            if not text:
                continue
            candidate = Path(text).expanduser()
            workspace_app_root = app_root_from_workspace_member(candidate)
            base = workspace_app_root or (candidate.parent if candidate.name.lower() in known_root_names else candidate)
            suggested = suggested_workspace_paths(base).get(key)
            if suggested is not None:
                return suggested
        return None

    def _ensure_workflow_root_path(
        self,
        edit: QLineEdit,
        *,
        key: str,
        label: str,
    ) -> Optional[Path]:
        existing_text = edit.text().strip()
        if existing_text:
            return Path(existing_text).expanduser()
        suggested = self._suggest_workflow_root_path(key)
        if suggested is None:
            QMessageBox.warning(
                self,
                APP_TITLE,
                f"{label} is not configured.\n\nInitialize a workspace or set the path manually before sending editor output to Texture Workflow.",
            )
            self.set_status_message(f"{label} is not configured.", error=True)
            return None
        suggested.mkdir(parents=True, exist_ok=True)
        edit.setText(str(suggested))
        self.append_log(f"Auto-configured {label}: {suggested}")
        self.set_status_message(f"Auto-configured {label}: {suggested}")
        return suggested

    def _open_source_in_texture_editor(self, source_path_text: str, binding: object) -> None:
        if not source_path_text:
            self.set_status_message("No source file was provided for Texture Editor.", error=True)
            return
        source_path = Path(source_path_text).expanduser()
        if not source_path.exists():
            self.set_status_message(f"Texture Editor source not found: {source_path}", error=True)
            return
        texture_binding = binding if isinstance(binding, TextureEditorSourceBinding) else None
        self._activate_tool_widget(self.texture_editor_tab)
        self.texture_editor_tab.open_source_path(source_path, binding=texture_binding)

    def _open_recolor_variant_target_in_texture_editor(
        self,
        source_path_text: str,
        binding: object,
        tool_settings: object,
    ) -> None:
        self._open_source_in_texture_editor(source_path_text, binding)
        if not isinstance(tool_settings, TextureEditorToolSettings):
            return
        if not hasattr(self.texture_editor_tab, "set_recolor_tool_settings"):
            return
        self.texture_editor_tab.set_recolor_tool_settings(
            mode=tool_settings.recolor_mode,
            source_color=tool_settings.recolor_source_hex,
            target_color=tool_settings.recolor_target_hex,
            tolerance=tool_settings.recolor_tolerance,
            strength=tool_settings.recolor_strength,
            preserve_luminance=tool_settings.recolor_preserve_luminance,
        )

    def _show_archive_browser_from_texture_editor(self, archive_relative_path: str = "") -> None:
        self._activate_tool_widget(self.archive_browser_tab)
        normalized_path = PurePosixPath(str(archive_relative_path or "").replace("\\", "/")).as_posix().strip()
        if not self.archive_entries:
            QMessageBox.information(
                self,
                "Archive Browser",
                "Archive packages are not loaded yet. Open Archive Browser and scan or load the archive cache first.",
            )
            self.set_status_message("Archive Browser is open. Load or refresh archive packages to browse DDS files.")
            return
        if normalized_path:
            preferred_index = next(
                (index for index, entry in enumerate(self.archive_filtered_entries) if entry.path == normalized_path),
                -1,
            )
            if preferred_index >= 0:
                target_item = self._select_archive_tree_entry(preferred_index)
                if target_item is not None:
                    self.archive_tree.setCurrentItem(target_item)
                    target_item.setSelected(True)
                    self.archive_tree.scrollToItem(target_item, QAbstractItemView.PositionAtCenter)
                    self.set_status_message(f"Focused Archive Browser on {normalized_path}.")
                    return
            matching_entry = next((entry for entry in self.archive_entries if entry.path == normalized_path), None)
            if matching_entry is not None:
                if self.worker_thread is not None:
                    self.set_status_message(
                        "Archive Browser is busy. Wait for the current task to finish, then try again.",
                        error=True,
                    )
                    return
                self.archive_filter_edit.clear()
                self.archive_exclude_filter_edit.clear()
                self.archive_package_filter_edit.clear()
                self.archive_active_asset_catalog_scope = ""
                self.archive_clear_asset_scope_button.setVisible(False)
                self.archive_filter_edit.setPlaceholderText("Include path/item-name filter or glob, e.g. Vow of the Dead King or */texture/*")
                self.archive_structure_filter_pending_value = ARCHIVE_STRUCTURE_FILTER
                self._rebuild_archive_structure_filter_controls(ARCHIVE_STRUCTURE_FILTER)
                self._set_combo_by_value(self.archive_role_filter_combo, ARCHIVE_ROLE_FILTER)
                self.archive_exclude_common_technical_checkbox.setChecked(False)
                self.archive_min_size_spin.setValue(ARCHIVE_MIN_SIZE_KB)
                self.archive_previewable_only_checkbox.setChecked(False)
                self._rebuild_archive_extension_filter_choices(matching_entry.extension)
                self._set_combo_by_value(self.archive_extension_filter_combo, matching_entry.extension)
                self._save_settings()
                self.archive_filters_dirty = False
                self._update_archive_filter_button_state()
                self._start_archive_filter_worker(normalized_path)
                self.set_status_message(f"Revealing {normalized_path} in Archive Browser...")
                return
            else:
                self.set_status_message(
                    f"Archive Browser is open. Could not find {normalized_path} in the loaded archive index.",
                    error=True,
                )
        else:
            self.set_status_message("Archive Browser is open. Select a DDS file and use 'Open in Texture Editor'.")

    def _open_archive_entry_in_texture_editor(self, entry: ArchiveEntry) -> None:
        try:
            source_path, _note = ensure_archive_preview_source(entry)
        except Exception as exc:
            self.set_status_message(f"Could not open archive file in Texture Editor: {exc}", error=True)
            return
        package_root = entry.pamt_path.parent.name.strip() or "package"
        archive_relative_path = PurePosixPath(entry.path.replace("\\", "/")).as_posix()
        binding = TextureEditorSourceBinding(
            launch_origin="archive_browser",
            display_name=entry.basename,
            source_path=str(source_path),
            relative_path=str(Path(package_root) / Path(PurePosixPath(archive_relative_path))),
            package_root=package_root,
            archive_relative_path=archive_relative_path,
            original_dds_path=str(source_path) if source_path.suffix.lower() == ".dds" else "",
        )
        self._open_source_in_texture_editor(str(source_path), binding)

    def _open_archive_current_in_texture_editor(self) -> None:
        entry = self._current_archive_entry()
        if entry is None:
            self.set_status_message("Select an archive file first.", error=True)
            return
        self._open_archive_entry_in_texture_editor(entry)

    def _resolve_archive_current_in_research(self) -> None:
        entry = self._current_archive_entry()
        if entry is None or entry.extension != ".dds":
            self.set_status_message("Select a single archive DDS file first.", error=True)
            return
        self._activate_tool_widget(self.research_tab)
        self.research_tab.focus_references_for_path(entry.path, auto_resolve=True)

    def _open_compare_in_texture_editor(self) -> None:
        relative_path = self.current_compare_path_for_research().strip()
        if not relative_path:
            self.set_status_message("Select a DDS file in Compare first.", error=True)
            return
        original_root_text = self.original_dds_edit.text().strip()
        output_root_text = self.output_root_edit.text().strip()
        relative = Path(PurePosixPath(relative_path))
        original_path = Path(original_root_text).expanduser() / relative if original_root_text else None
        output_path = Path(output_root_text).expanduser() / relative if output_root_text else None
        source_path = output_path if output_path is not None and output_path.exists() else original_path
        if source_path is None or not source_path.exists():
            self.set_status_message("Could not find a compare source file to open in Texture Editor.", error=True)
            return
        binding = self._build_texture_editor_binding_for_loose_path(
            source_path,
            launch_origin="compare",
            original_dds_path=original_path if original_path is not None and original_path.exists() else None,
        )
        self._open_source_in_texture_editor(str(source_path), binding)

    def _browse_texture_editor_source(self) -> None:
        initial_dir = self.png_root_edit.text().strip() or self.original_dds_edit.text().strip() or str(self.settings_file_path.parent)
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open image or DDS in Texture Editor",
            initial_dir,
            "Supported files (*.png *.dds *.jpg *.jpeg *.bmp *.tga *.webp);;All files (*.*)",
        )
        if not file_path:
            return
        source_path = Path(file_path)
        binding = self._build_texture_editor_binding_for_loose_path(source_path, launch_origin="texture_workflow")
        self._open_source_in_texture_editor(str(source_path), binding)

    def _set_texture_editor_export_progress(self, detail: str) -> None:
        self.reset_progress()
        self.phase_value.setText("Texture Editor Export")
        self.phase_progress_value.setText(detail)
        self.current_file_value.setText(detail)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("Working...")

    def _set_replace_assistant_pending_status(self, detail: str) -> None:
        self.replace_assistant_tab.progress_bar.setRange(0, 0)
        self.replace_assistant_tab.progress_bar.setValue(0)
        self.replace_assistant_tab.progress_bar.setFormat("Working...")
        self.replace_assistant_tab.status_label.setText(detail)

    def _set_replace_assistant_ready_status(self, detail: str) -> None:
        self.replace_assistant_tab.progress_bar.setRange(0, 1)
        self.replace_assistant_tab.progress_bar.setValue(1)
        self.replace_assistant_tab.progress_bar.setFormat("Ready")
        self.replace_assistant_tab.status_label.setText(detail)

    def _normalize_texture_workflow_relative_path(self, raw_text: str) -> str:
        normalized = str(raw_text or "").strip().replace("\\", "/").strip()
        if not normalized:
            raise ValueError("Relative game path is required.")
        if normalized.startswith("/"):
            raise ValueError("Relative game path must not be absolute.")
        pure_path = PurePosixPath(normalized)
        if any(part in {"", ".", ".."} for part in pure_path.parts):
            raise ValueError("Relative game path must not contain '.' or '..' segments.")
        if pure_path.suffix.lower() != ".dds":
            pure_path = pure_path.with_suffix(".dds")
        return pure_path.as_posix()

    def _find_archive_entry_for_workflow_relative_path(self, relative_path_text: str) -> Optional[ArchiveEntry]:
        if not self.archive_entries:
            return None
        try:
            normalized_relative = self._normalize_texture_workflow_relative_path(relative_path_text)
        except ValueError:
            return None
        pure_path = PurePosixPath(normalized_relative)
        parts = [part for part in pure_path.parts if part]
        if not parts:
            return None
        package_root = parts[0] if len(parts) > 1 else ""
        archive_relative = PurePosixPath(*parts[1:]).as_posix() if len(parts) > 1 else pure_path.as_posix()
        normalized_archive_relative = archive_relative.replace("\\", "/").strip().casefold()
        normalized_package_root = package_root.strip().casefold()
        for entry in self.archive_entries:
            if entry.extension != ".dds":
                continue
            if entry.path.replace("\\", "/").strip().casefold() != normalized_archive_relative:
                continue
            if normalized_package_root and entry.pamt_path.parent.name.strip().casefold() != normalized_package_root:
                continue
            return entry
        return None

    def _resolve_original_dds_from_archive_cache(self, relative_path_text: str) -> Optional[Path]:
        entry = self._find_archive_entry_for_workflow_relative_path(relative_path_text)
        if entry is None:
            return None
        try:
            try:
                source_path, _note = ensure_archive_preview_source(entry)
            except Exception:
                return None
            if source_path.exists() and source_path.is_file():
                return source_path.expanduser().resolve()
            return None
        except Exception:
            return None
