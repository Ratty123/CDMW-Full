"""Texture editor outbound handoff helpers for workflow and related tools."""

from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.constants import (
    MOD_READY_PACKAGE_AUTHOR,
    MOD_READY_PACKAGE_DESCRIPTION,
    MOD_READY_PACKAGE_NEXUS_URL,
    MOD_READY_PACKAGE_TITLE,
    MOD_READY_PACKAGE_VERSION,
    UPSCALE_BACKEND_CHAINNER,
)
from cdmw.core.archive import (
    clear_directory_contents,
    directory_has_contents,
    extract_archive_entries,
    extract_archive_entry,
)
from cdmw.core.mod_package import resolve_mod_package_root
from cdmw.models import AppConfig, ArchiveEntry, ModPackageInfo, TextureEditorSourceBinding


class TextureWorkflowEditorHandoffMixin:
    """Route Texture Editor outputs into workflow, compare, and icon surfaces."""

    def _prompt_texture_editor_workflow_target(
        self,
        source_path: Path,
        *,
        initial_relative_path: str,
        initial_original_dds_path: str,
    ) -> Optional[Tuple[str, Path]]:
        dialog = QDialog(self)
        dialog.setWindowTitle("Texture Workflow Target")
        dialog.setModal(True)
        dialog.resize(620, 180)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        info_label = QLabel(
            "This image was opened as a loose external file, so Texture Workflow needs an explicit game-relative target path and the original DDS source."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        form_layout = QGridLayout()
        form_layout.setHorizontalSpacing(8)
        form_layout.setVerticalSpacing(8)
        normalized_initial_relative = initial_relative_path.strip() or f"{source_path.stem}.dds"
        try:
            normalized_initial_relative = self._normalize_texture_workflow_relative_path(normalized_initial_relative)
        except ValueError:
            normalized_initial_relative = initial_relative_path.strip() or f"{source_path.stem}.dds"
        relative_edit = QLineEdit(normalized_initial_relative)
        original_edit = QLineEdit(initial_original_dds_path.strip())
        browse_original_button = QPushButton("Browse...")
        find_archive_button = QPushButton("Find In Archive")
        form_layout.addWidget(QLabel("Relative game path"), 0, 0)
        form_layout.addWidget(relative_edit, 0, 1, 1, 3)
        form_layout.addWidget(QLabel("Original DDS path"), 1, 0)
        form_layout.addWidget(original_edit, 1, 1)
        form_layout.addWidget(browse_original_button, 1, 2)
        form_layout.addWidget(find_archive_button, 1, 3)
        form_layout.setColumnStretch(1, 1)
        layout.addLayout(form_layout)
        match_hint_label = QLabel("")
        match_hint_label.setWordWrap(True)
        match_hint_label.setObjectName("HintLabel")
        layout.addWidget(match_hint_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        continue_button = QPushButton("Send To Workflow")
        continue_button.setDefault(True)
        button_row.addWidget(cancel_button)
        button_row.addWidget(continue_button)
        layout.addLayout(button_row)

        result: List[object] = []

        def _browse_original() -> None:
            initial_dir = original_edit.text().strip() or self.original_dds_edit.text().strip() or str(source_path.parent)
            selected, _ = QFileDialog.getOpenFileName(
                dialog,
                "Select Original DDS",
                initial_dir,
                "DDS files (*.dds);;All files (*.*)",
            )
            if selected:
                original_edit.setText(selected)

        def _try_fill_original_from_archive(*, show_feedback: bool) -> bool:
            resolved_original = self._resolve_original_dds_from_archive_cache(relative_edit.text())
            if resolved_original is None:
                if show_feedback:
                    if not self.archive_entries:
                        match_hint_label.setText(
                            "Archive cache is not loaded. Load archives first if you want automatic DDS lookup."
                        )
                    else:
                        match_hint_label.setText(
                            "No exact DDS match was found in the loaded archive cache for the current relative path."
                        )
                return False
            original_edit.setText(str(resolved_original))
            match_hint_label.setText(f"Matched original DDS from loaded archive cache: {resolved_original}")
            return True

        def _accept() -> None:
            try:
                normalized_relative_path = self._normalize_texture_workflow_relative_path(relative_edit.text())
            except ValueError as exc:
                QMessageBox.warning(dialog, "Texture Workflow Target", str(exc))
                return
            original_text = original_edit.text().strip()
            if not original_text:
                _try_fill_original_from_archive(show_feedback=False)
                original_text = original_edit.text().strip()
            if not original_text:
                QMessageBox.warning(dialog, "Texture Workflow Target", "Original DDS path is required.")
                return
            original_path = Path(original_text).expanduser()
            if not original_path.exists() or not original_path.is_file():
                QMessageBox.warning(dialog, "Texture Workflow Target", f"Original DDS file was not found:\n{original_path}")
                return
            result[:] = [normalized_relative_path, original_path.resolve()]
            dialog.accept()

        browse_original_button.clicked.connect(_browse_original)
        find_archive_button.clicked.connect(lambda: _try_fill_original_from_archive(show_feedback=True))
        cancel_button.clicked.connect(dialog.reject)
        continue_button.clicked.connect(_accept)
        if not original_edit.text().strip():
            _try_fill_original_from_archive(show_feedback=bool(relative_edit.text().strip()))

        if dialog.exec() != QDialog.Accepted or len(result) != 2:
            return None
        return str(result[0]), Path(result[1])

    def _confirm_texture_editor_workflow_overwrite(self, destination: Path) -> bool:
        if not destination.exists():
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Texture Editor PNG Root Already Contains This File")
        box.setIcon(QMessageBox.Question)
        box.setText("The matching PNG path already exists in the Texture Editor PNG root.")
        box.setInformativeText(
            f"{destination}\n\n"
            "Texture Workflow needs this exact relative path, so the export cannot be renamed here. "
            "Choose whether to overwrite the existing PNG or cancel."
        )
        overwrite_button = box.addButton("Overwrite Existing", QMessageBox.AcceptRole)
        cancel_button = box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(overwrite_button)
        box.exec()
        return box.clickedButton() != cancel_button

    def _prompt_texture_editor_workflow_root_action(
        self,
        root_path: Path,
        *,
        root_label: str,
        staged_item_label: str,
        keep_existing_note: str = "",
    ) -> Optional[bool]:
        if not self._directory_has_contents(root_path):
            return False
        box = QMessageBox(self)
        box.setWindowTitle(f"{root_label} Already Contains Files")
        box.setIcon(QMessageBox.Question)
        box.setText(f"{root_label} already contains files or folders.")
        info_lines = [
            str(root_path),
            "",
            f"Choose whether to clear it before staging this {staged_item_label}.",
        ]
        note_text = str(keep_existing_note or "").strip()
        if note_text:
            info_lines.append(note_text)
        info_lines.append("Choose Keep Existing to leave the current contents in place, or Cancel to stop.")
        box.setInformativeText("\n".join(info_lines))
        clear_button = box.addButton("Clear Root", QMessageBox.DestructiveRole)
        keep_button = box.addButton("Keep Existing", QMessageBox.AcceptRole)
        cancel_button = box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(keep_button)
        box.exec()
        clicked = box.clickedButton()
        if clicked == cancel_button:
            return None
        return clicked == clear_button

    def _set_pending_texture_editor_workflow_export(
        self,
        *,
        source_png: Path,
        destination_png: Path,
        relative_path: str,
    ) -> None:
        self._pending_texture_editor_workflow_export = {
            "source_png": str(source_png.expanduser().resolve()),
            "destination_png": str(destination_png.expanduser().resolve()),
            "relative_path": relative_path,
        }

    def _has_pending_texture_editor_workflow_export_for_root(self, root_path: Path) -> bool:
        payload = self._pending_texture_editor_workflow_export
        if not isinstance(payload, dict):
            return False
        destination_text = str(payload.get("destination_png", "")).strip()
        if not destination_text:
            return False
        try:
            return Path(destination_text).expanduser().resolve().is_relative_to(root_path.expanduser().resolve())
        except Exception:
            return False

    def _apply_pending_texture_editor_workflow_export_if_needed(self, *, force: bool = False) -> bool:
        payload = self._pending_texture_editor_workflow_export
        if not isinstance(payload, dict):
            return False
        source_text = str(payload.get("source_png", "")).strip()
        destination_text = str(payload.get("destination_png", "")).strip()
        if not source_text or not destination_text:
            return False
        source_path = Path(source_text).expanduser()
        destination_path = Path(destination_text).expanduser()
        if not source_path.exists():
            return False
        if not force and destination_path.exists():
            return False
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        self.append_log(f"Restored pending Texture Editor PNG into workflow root: {destination_path}")
        return True

    def _set_pending_archive_workflow_extract(
        self,
        *,
        entries: Sequence[ArchiveEntry],
        output_root: Path,
    ) -> None:
        self._pending_archive_workflow_extract = {
            "entries": [entry for entry in entries if isinstance(entry, ArchiveEntry)],
            "output_root": str(output_root.expanduser().resolve()),
        }

    def _has_pending_archive_workflow_extract_for_root(self, root_path: Path) -> bool:
        payload = self._pending_archive_workflow_extract
        if not isinstance(payload, dict):
            return False
        output_root_text = str(payload.get("output_root", "")).strip()
        if not output_root_text:
            return False
        try:
            return Path(output_root_text).expanduser().resolve() == root_path.expanduser().resolve()
        except Exception:
            return False

    def _apply_pending_archive_workflow_extract_if_needed(self, *, force: bool = False) -> bool:
        payload = self._pending_archive_workflow_extract
        if not isinstance(payload, dict):
            return False
        output_root_text = str(payload.get("output_root", "")).strip()
        entries = payload.get("entries", [])
        if not output_root_text or not isinstance(entries, list) or not entries:
            return False
        output_root = Path(output_root_text).expanduser()
        if not force and output_root.exists() and directory_has_contents(output_root):
            return False
        output_root.mkdir(parents=True, exist_ok=True)
        self.append_log(f"Restoring pending archive DDS handoff into workflow source root: {output_root}")
        extract_archive_entries(entries, output_root, collision_mode="overwrite", on_log=self.append_log)
        return True

    def _workflow_start_cleanup_targets(
        self,
        config: AppConfig,
        *,
        include_output_root: bool,
    ) -> List[Tuple[str, str, Path]]:
        targets: List[Tuple[str, str, Path]] = []
        should_prompt_for_png_root = config.enable_dds_staging or config.upscale_backend == UPSCALE_BACKEND_CHAINNER
        if should_prompt_for_png_root:
            png_root_text = config.png_root.strip()
            if png_root_text:
                targets.append(("png_root", "PNG root", Path(png_root_text).expanduser()))
        if include_output_root:
            output_root_text = config.output_root.strip()
            if output_root_text:
                targets.append(("output_root", "Output root", Path(output_root_text).expanduser()))
        if getattr(config, "enable_mod_ready_loose_export", False):
            export_root_text = str(getattr(config, "mod_ready_export_root", "") or "").strip()
            if export_root_text:
                package_info = ModPackageInfo(
                    title=str(getattr(config, "mod_ready_package_title", MOD_READY_PACKAGE_TITLE) or "").strip() or MOD_READY_PACKAGE_TITLE,
                    version=str(getattr(config, "mod_ready_package_version", MOD_READY_PACKAGE_VERSION) or "").strip() or MOD_READY_PACKAGE_VERSION,
                    author=str(getattr(config, "mod_ready_package_author", MOD_READY_PACKAGE_AUTHOR) or "").strip(),
                    description=str(getattr(config, "mod_ready_package_description", MOD_READY_PACKAGE_DESCRIPTION) or "").strip(),
                    nexus_url=str(getattr(config, "mod_ready_package_nexus_url", MOD_READY_PACKAGE_NEXUS_URL) or "").strip(),
                )
                targets.append(
                    (
                        "mod_ready_output",
                        "Ready mod package output",
                        resolve_mod_package_root(Path(export_root_text).expanduser(), package_info),
                    )
                )
        return targets

    def _manual_workflow_cleanup_targets(self) -> List[Tuple[str, str, Optional[Path]]]:
        targets: List[Tuple[str, str, Optional[Path]]] = []
        for key, label, text in (
            ("rebuilt_textures", "Rebuilt textures", self.output_root_edit.text().strip()),
            ("original_dds", "Original DDS sources", self.original_dds_edit.text().strip()),
            ("dds_input_png", "DDS input PNG staging", self.dds_staging_root_edit.text().strip()),
            ("upscaled_png", "Upscaled PNG staging", self.png_root_edit.text().strip()),
            ("texture_editor_png", "Texture Editor PNG staging", self.texture_editor_png_root_edit.text().strip()),
        ):
            targets.append((key, label, Path(text).expanduser() if text else None))
        return targets

    def _handle_texture_editor_send_to_replace_assistant(self, png_path_text: str, binding: object) -> None:
        source_path = Path(png_path_text).expanduser()
        if not source_path.exists():
            self.set_status_message(f"Texture Editor export not found: {source_path}", error=True)
            return
        del binding
        self._activate_tool_widget(self.replace_assistant_tab)
        self.replace_assistant_tab.import_external_sources(
            [source_path],
            select_path=source_path,
        )
        self.set_status_message(
            f"Texture Editor export imported into Texture Replacer: {source_path.name}"
        )

    def _handle_texture_editor_send_to_texture_workflow(self, png_path_text: str, binding: object) -> None:
        texture_editor_png_root = self._ensure_workflow_root_path(
            self.texture_editor_png_root_edit,
            key="texture_editor_png_root",
            label="Texture Editor PNG root",
        )
        if texture_editor_png_root is None:
            return
        source_path = Path(png_path_text).expanduser()
        if not source_path.exists():
            self.set_status_message(f"Texture Editor export not found: {source_path}", error=True)
            return
        texture_binding = binding if isinstance(binding, TextureEditorSourceBinding) else TextureEditorSourceBinding()
        original_root = self._ensure_workflow_root_path(
            self.original_dds_edit,
            key="original_dds_root",
            label="Original DDS root",
        )
        if original_root is None:
            return
        relative_path = texture_binding.relative_path.strip()
        original_dds_source_text = texture_binding.original_dds_path.strip()
        original_dds_source: Optional[Path] = None

        if relative_path and original_dds_source_text:
            original_dds_source = Path(original_dds_source_text).expanduser()
            if not original_dds_source.exists():
                self.set_status_message(
                    f"Texture Editor original DDS source not found: {original_dds_source}",
                    error=True,
                )
                return
            relative_path = self._normalize_texture_workflow_relative_path(relative_path)
        else:
            target_result = self._prompt_texture_editor_workflow_target(
                source_path,
                initial_relative_path=relative_path,
                initial_original_dds_path=original_dds_source_text,
            )
            if target_result is None:
                self.set_status_message("Texture Editor export to Texture Workflow cancelled.")
                return
            relative_path, original_dds_source = target_result

        resolved_destination = (
            texture_editor_png_root.expanduser()
            / Path(PurePosixPath(relative_path)).with_suffix(".png")
        )
        clear_texture_editor_root = self._prompt_texture_editor_workflow_root_action(
            texture_editor_png_root.expanduser(),
            root_label="Texture Editor PNG root",
            staged_item_label="Texture Editor export",
        )
        if clear_texture_editor_root is None:
            self.set_status_message("Texture Editor export to Texture Workflow cancelled.")
            return
        if not clear_texture_editor_root and not self._confirm_texture_editor_workflow_overwrite(resolved_destination):
            self.set_status_message("Texture Editor export to Texture Workflow cancelled.")
            return
        original_destination = original_root.expanduser() / Path(PurePosixPath(relative_path)).with_suffix(".dds")
        clear_original_root = self._prompt_texture_editor_workflow_root_action(
            original_root.expanduser(),
            root_label="Original DDS root",
            staged_item_label="matching original DDS",
            keep_existing_note=(
                "Choose Clear Root if you want to remove stale DDS files before sending this texture to Texture Workflow."
            ),
        )
        if clear_original_root is None:
            self.set_status_message("Texture Editor export to Texture Workflow cancelled.")
            return
        self._activate_tool_widget(self.workflow_tab)
        self.content_tabs.setCurrentIndex(0)
        self._set_texture_editor_export_progress("Staging flattened PNG for Texture Workflow...")
        self.set_status_message("Staging Texture Editor export for Texture Workflow...")

        def task(on_log: Callable[[str], None]) -> Dict[str, str]:
            resolved_source = source_path.expanduser().resolve()
            if not resolved_source.exists():
                raise FileNotFoundError(f"Texture Editor export not found: {resolved_source}")
            assert original_dds_source is not None
            resolved_original_dds = original_dds_source.expanduser().resolve()
            archive_entry = self._find_archive_entry_for_workflow_relative_path(relative_path)
            original_root_resolved = original_root.expanduser().resolve()
            original_bytes_from_source: Optional[bytes] = None
            if clear_original_root and resolved_original_dds.exists():
                try:
                    if resolved_original_dds.is_relative_to(original_root_resolved):
                        original_bytes_from_source = resolved_original_dds.read_bytes()
                except Exception:
                    original_bytes_from_source = None
            if not resolved_original_dds.exists() and archive_entry is None and original_bytes_from_source is None:
                raise FileNotFoundError(f"Texture Editor original DDS source not found: {resolved_original_dds}")
            final_destination = resolved_destination.expanduser()
            if clear_texture_editor_root:
                final_root = texture_editor_png_root.expanduser()
                final_root.mkdir(parents=True, exist_ok=True)
                on_log(f"Clearing Texture Editor PNG root before staging export: {final_root}")
                clear_directory_contents(final_root)
            final_destination.parent.mkdir(parents=True, exist_ok=True)
            on_log(f"Copying Texture Editor export into Texture Editor PNG root: {resolved_source.name} -> {final_destination}")
            shutil.copy2(resolved_source, final_destination)
            final_original_destination = original_destination.expanduser()
            if clear_original_root:
                final_original_root = original_root.expanduser()
                final_original_root.mkdir(parents=True, exist_ok=True)
                on_log(f"Clearing Original DDS root before staging source DDS: {final_original_root}")
                clear_directory_contents(final_original_root)
            final_original_destination.parent.mkdir(parents=True, exist_ok=True)
            if final_original_destination.exists():
                on_log(
                    f"Refreshing matching original DDS in workflow source root: {resolved_original_dds.name} -> {final_original_destination}"
                )
            else:
                on_log(
                    f"Staging matching original DDS into workflow source root: {resolved_original_dds.name} -> {final_original_destination}"
                )
            if original_bytes_from_source is not None:
                final_original_destination.write_bytes(original_bytes_from_source)
            elif resolved_original_dds.exists():
                shutil.copy2(resolved_original_dds, final_original_destination)
            elif archive_entry is not None:
                extract_archive_entry(archive_entry, final_original_destination)
            else:
                raise FileNotFoundError(f"Texture Editor original DDS source not found: {resolved_original_dds}")
            return {
                "destination": str(final_destination),
                "source": str(resolved_source),
                "original_destination": str(final_original_destination),
                "original_source": str(resolved_original_dds),
            }

        def on_complete(result: object) -> None:
            payload = result if isinstance(result, dict) else {}
            destination_text = str(payload.get("destination", "")).strip()
            destination_path = Path(destination_text).expanduser() if destination_text else resolved_destination
            self._set_pending_texture_editor_workflow_export(
                source_png=source_path.expanduser(),
                destination_png=destination_path,
                relative_path=relative_path,
            )
            self._pending_archive_workflow_extract = None
            self.filters_edit.setPlainText(relative_path)
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1)
            self.progress_bar.setFormat("Ready")
            self.phase_value.setText("Idle")
            self.phase_progress_value.setText("Ready")
            self.current_file_value.setText("Idle")
            self._activate_tool_widget(self.workflow_tab)
            self.content_tabs.setCurrentIndex(0)
            self.set_status_message(
                f"Texture Editor export staged for Workflow in Texture Editor PNG root and filter focused on {relative_path}.",
                error=False,
            )

        self._run_utility_task(
            status_message="Staging Texture Editor export for Texture Workflow...",
            task=task,
            on_complete=on_complete,
        )

    def _handle_texture_editor_send_to_item_icons(self, png_path_text: str, binding: object) -> None:
        source_path = Path(png_path_text).expanduser()
        if not source_path.exists():
            self.set_status_message(f"Texture Editor export not found: {source_path}", error=True)
            return
        del binding
        try:
            imported_path = self.item_icons_tab.add_imported_source(source_path)
        except Exception as exc:
            self.set_status_message(f"Texture Editor export could not be added to Icon Creator: {exc}", error=True)
            return
        self._activate_tool_widget(self.item_icons_tab)
        if imported_path is not None:
            self.item_icons_tab.select_source_path(imported_path)
            self.set_status_message(f"Texture Editor export added to Icon Creator: {Path(imported_path).name}")

    def _handle_model_library_item_icon_generated(self, png_path_text: str, model_payload: object) -> None:
        source_path = Path(png_path_text).expanduser()
        if not source_path.is_file():
            self.set_status_message(f"Generated model icon was not found: {source_path}", error=True)
            return
        try:
            imported_path = self.item_icons_tab.add_imported_source(source_path)
        except Exception as exc:
            self.set_status_message(f"Generated model icon could not be added to Icon Creator: {exc}", error=True)
            return
        self._activate_tool_widget(self.item_icons_tab)
        if imported_path is not None:
            self.item_icons_tab.select_source_path(imported_path)
        metadata = model_payload if isinstance(model_payload, Mapping) else {}
        model_name = str(metadata.get("name", "") or source_path.stem).strip()
        self.set_status_message(f"Generated model preview icon added to Icon Creator: {model_name}.")

    def _choose_item_icon_library_source(self, parent: Optional[QWidget] = None) -> Optional[Path]:
        tab = getattr(self, "item_icons_tab", None)
        if tab is None:
            self.set_status_message("Icon Creator library is unavailable.", error=True)
            return None
        try:
            return tab.choose_source_dialog(parent)
        except Exception as exc:
            QMessageBox.warning(parent or self, "Icon Creator", str(exc))
            self.set_status_message(f"Icon Creator library picker failed: {exc}", error=True)
            return None

    def _show_compare_from_texture_editor(self, relative_path_text: str, binding: object) -> None:
        texture_binding = binding if isinstance(binding, TextureEditorSourceBinding) else TextureEditorSourceBinding()
        compare_path = str(relative_path_text or "").strip()
        if not compare_path:
            compare_path = (texture_binding.relative_path or texture_binding.archive_relative_path).strip()
        if not compare_path:
            self.set_status_message(
                "Texture Editor could not determine a relative game path for Compare.",
                error=True,
            )
            return
        self._activate_tool_widget(self.workflow_tab)
        self.content_tabs.setCurrentWidget(self.compare_tab)
        self.refresh_compare_list(select_current=True)
        target_item = None
        for row in range(self.compare_list.count()):
            item = self.compare_list.item(row)
            if item is not None and str(item.data(Qt.UserRole) or "").strip() == compare_path:
                target_item = item
                break
        if target_item is None:
            self.set_status_message(
                "Compare is open, but the current compare roots do not contain this texture yet.",
                error=True,
            )
            return
        self.compare_list.setCurrentItem(target_item)
        self.compare_list.scrollToItem(target_item, QAbstractItemView.PositionAtCenter)
        self.set_status_message(f"Focused Compare on {compare_path}.", error=False)




__all__ = ["TextureWorkflowEditorHandoffMixin"]
