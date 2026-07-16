"""Workspace setup, cleanup, and model import actions for the shell."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from cdmw.constants import (
    CHAINNER_DOWNLOAD_PAGE_URL,
    REALESRGAN_NCNN_RELEASES_PAGE_URL,
)
from cdmw.services.archive_extraction_service import clear_directory_contents
from cdmw.services.texture_workflow_service import import_model_assets_to_directory, validate_ncnn_model_import_sources
from cdmw.services.texture_workflow_service import (
    common_workspace_root_from_config,
    create_missing_directories_for_config,
    create_workspace_structure,
    suggested_workspace_paths,
)


class WorkspaceControllerMixin:
    """Workflow folder setup, cleanup prompts, and auxiliary model imports."""

    def _directory_has_contents(self, path: Path) -> bool:
        try:
            if not path.exists() or not path.is_dir():
                return False
            next(path.iterdir())
            return True
        except StopIteration:
            return False
        except OSError:
            return False

    def _prompt_clear_directory_before_start(self, label: str, path: Path) -> Optional[bool]:
        if not self._directory_has_contents(path):
            return False

        box = QMessageBox(self)
        box.setWindowTitle(f"{label} Not Empty")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"{label} already contains files or folders.")
        box.setInformativeText(
            f"{path}\n\n"
            "Clear it before starting?\n"
            "Choose Keep Existing to leave the current contents in place, or Cancel to stop."
        )
        clear_button = box.addButton("Clear Folder", QMessageBox.DestructiveRole)
        keep_button = box.addButton("Keep Existing", QMessageBox.AcceptRole)
        cancel_button = box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(keep_button)
        box.exec()

        clicked = box.clickedButton()
        if clicked == cancel_button:
            return None
        return clicked == clear_button

    def _prepare_workflow_output_roots_for_start(
        self,
        config: object,
        *,
        include_output_root: bool,
    ) -> bool:
        if config.dry_run:
            return True

        targets = self._workflow_start_cleanup_targets(
            config,
            include_output_root=include_output_root,
        )

        seen_paths: set[str] = set()
        unique_targets: List[Tuple[str, str, Path]] = []
        for key, label, path in targets:
            try:
                normalized_key = str(path.resolve())
            except OSError:
                normalized_key = str(path)
            if normalized_key in seen_paths:
                continue
            seen_paths.add(normalized_key)
            unique_targets.append((key, label, path))

        cleared_target_keys: set[str] = set()
        for key, label, path in unique_targets:
            if not self._preference_bool("confirm_workflow_output_cleanup", True):
                self.append_log(f"Keeping existing contents in {label}: {path} (cleanup confirmation disabled)")
                continue
            decision = self._prompt_clear_directory_before_start(label, path)
            if decision is None:
                self.set_status_message("Start cancelled.")
                self.append_log(f"Start cancelled while reviewing {label.lower()} contents.")
                return False
            if not decision:
                self.append_log(f"Keeping existing contents in {label}: {path}")
                continue
            path.mkdir(parents=True, exist_ok=True)
            clear_directory_contents(path)
            self.append_log(f"Cleared {label} before start: {path}")
            cleared_target_keys.add(key)

        if "input_dds" in cleared_target_keys:
            self._apply_pending_archive_workflow_extract_if_needed(force=True)
        if "texture_editor_png_root" in cleared_target_keys:
            self._apply_pending_texture_editor_workflow_export_if_needed(force=True)

        return True

    def clear_workflow_roots(self) -> None:
        targets = self._manual_workflow_cleanup_targets()
        lines: List[str] = []
        configured_targets: List[Tuple[str, Path]] = []
        seen_paths: set[str] = set()
        for key, label, path in targets:
            if path is None:
                lines.append(f"- {label}: not configured")
                continue
            try:
                resolved_path = path.resolve()
            except OSError:
                resolved_path = path
            lines.append(f"- {label}: {resolved_path}")
            normalized_key = str(resolved_path)
            if normalized_key in seen_paths:
                continue
            seen_paths.add(normalized_key)
            configured_targets.append((label, resolved_path))

        box = QMessageBox(self)
        box.setWindowTitle("Clear Workflow Roots")
        box.setIcon(QMessageBox.Warning)
        box.setText("This will clear the configured workflow staging/output folders listed below.")
        box.setInformativeText("\n".join(lines))
        clear_button = box.addButton("Clear Folders", QMessageBox.AcceptRole)
        cancel_button = box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(cancel_button)
        box.exec()
        if box.clickedButton() != clear_button:
            self.set_status_message("Workflow root cleanup cancelled.")
            return

        cleared_count = 0
        for label, resolved_path in configured_targets:
            resolved_path.mkdir(parents=True, exist_ok=True)
            clear_directory_contents(resolved_path)
            self.append_log(f"Cleared {label}: {resolved_path}")
            cleared_count += 1

        self.set_status_message(f"Cleared {cleared_count} configured workflow folder(s).")

    def initialize_workspace(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select Workspace Folder",
            self._suggest_workspace_base_dir(),
        )
        if not selected:
            return

        base_dir = Path(selected)

        def task(on_log: Callable[[str], None]) -> Dict[str, str]:
            on_log(f"Creating workspace structure under {base_dir}")
            paths = create_workspace_structure(base_dir)
            return {key: str(value) for key, value in paths.items()}

        def on_complete(result: object) -> None:
            if not isinstance(result, dict):
                return
            self.original_dds_edit.setText(str(result["original_dds_root"]))
            self.png_root_edit.setText(str(result["png_root"]))
            if not self.texture_editor_png_root_edit.text().strip():
                self.texture_editor_png_root_edit.setText(str(result["texture_editor_png_root"]))
            if not self.dds_staging_root_edit.text().strip():
                self.dds_staging_root_edit.setText(str(result["dds_staging_root"]))
            self.output_root_edit.setText(str(result["output_root"]))
            if not self.archive_extract_root_edit.text().strip():
                self.archive_extract_root_edit.setText(str(result["archive_extract_root"]))
            if not self.csv_log_path_edit.text().strip():
                self.csv_log_path_edit.setText(str(result["csv_log_path"]))
            if not self.chainner_exe_path_edit.text().strip():
                self.chainner_exe_path_edit.setText(str(result["chainner_exe_path"]))
            if not self.ncnn_exe_path_edit.text().strip():
                self.ncnn_exe_path_edit.setText(str(result["ncnn_exe_path"]))
            if not self.ncnn_model_dir_edit.text().strip():
                self.ncnn_model_dir_edit.setText(str(result["ncnn_model_dir"]))
            if not self.mod_ready_export_root_edit.text().strip():
                self.mod_ready_export_root_edit.setText(str(result["mod_ready_export_root"]))
            self._refresh_ncnn_model_picker()
            self.set_status_message(f"Workspace initialized at {base_dir}")
            self.append_log("Workspace initialization complete.")

        self._run_utility_task(
            status_message="Initializing workspace...",
            task=task,
            on_complete=on_complete,
        )

    def create_missing_folders(self) -> None:
        config = self.collect_config()

        def task(on_log: Callable[[str], None]) -> List[str]:
            created = create_missing_directories_for_config(config)
            if created:
                for path in created:
                    on_log(f"Created folder: {path}")
            else:
                on_log("No folders needed to be created.")
            return [str(path) for path in created]

        def on_complete(result: object) -> None:
            created = result if isinstance(result, list) else []
            if created:
                self.set_status_message(f"Created {len(created)} folder(s).")
            else:
                self.set_status_message("All requested folders already existed.")

        self._run_utility_task(
            status_message="Creating missing folders...",
            task=task,
            on_complete=on_complete,
        )

    def open_chainner_download_page(self) -> None:
        self._open_external_urls([CHAINNER_DOWNLOAD_PAGE_URL], label="chaiNNer")

    def open_realesrgan_ncnn_download_page(self) -> None:
        self._open_external_urls([REALESRGAN_NCNN_RELEASES_PAGE_URL], label="Real-ESRGAN NCNN")

    def _confirm_model_import_expectations(self, model_kind: str) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("Import NCNN Models")
        box.setText("Expected NCNN model contents")
        box.setInformativeText(
            "Choose a folder, zip, or file set that contains at least one matching "
            ".param + .bin pair with the same base name."
        )
        box.setDetailedText(
            "Example:\n"
            "  realesr-animevideov3.param\n"
            "  realesr-animevideov3.bin\n\n"
            "Nested folders inside a zip are fine.\n"
            "Unsupported examples include a single .param without its .bin partner,\n"
            "random checkpoint formats, or the NCNN executable folder without model files."
        )
        continue_button = box.addButton("Continue", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        return box.clickedButton() is continue_button

    def _choose_model_import_sources(self, title: str, *, model_kind: str) -> List[Path]:
        if not self._confirm_model_import_expectations(model_kind):
            return []
        mode, accepted = QInputDialog.getItem(
            self,
            title,
            "Import from:",
            ["Folder", "Files or zip"],
            0,
            False,
        )
        if not accepted or not mode:
            return []
        if mode == "Folder":
            selected = QFileDialog.getExistingDirectory(self, title, self._suggest_workspace_base_dir())
            return [Path(selected)] if selected else []
        selected_files, _ = QFileDialog.getOpenFileNames(
            self,
            title,
            self._suggest_workspace_base_dir(),
            "NCNN model files (*.param *.bin *.zip);;All files (*.*)",
        )
        return [Path(path) for path in selected_files]

    def _choose_model_destination(self, title: str, current_text: str) -> Optional[Path]:
        start_dir = self._pick_existing_directory(current_text) if current_text else self._suggest_workspace_base_dir()
        selected = QFileDialog.getExistingDirectory(self, title, start_dir)
        if not selected:
            return None
        return Path(selected)

    def import_ncnn_models(self) -> None:
        sources = self._choose_model_import_sources("Import NCNN Models", model_kind="ncnn")
        if not sources:
            return
        destination = self._choose_model_destination(
            "Select NCNN Model Folder",
            self.ncnn_model_dir_edit.text().strip(),
        )
        if destination is None:
            return

        def task(on_log: Callable[[str], None]) -> List[str]:
            pairs = validate_ncnn_model_import_sources(sources)
            on_log(f"Detected {len(pairs)} valid NCNN model pair(s): {', '.join(pairs[:5])}")
            imported = import_model_assets_to_directory(
                sources,
                destination,
                allowed_suffixes=(".param", ".bin"),
                on_log=on_log,
            )
            return [str(path) for path in imported]

        def on_complete(result: object) -> None:
            imported = result if isinstance(result, list) else []
            self.ncnn_model_dir_edit.setText(str(destination))
            self._refresh_ncnn_model_picker()
            self.set_status_message(f"Imported {len(imported)} NCNN model file(s).")

        self._run_utility_task(
            status_message="Importing NCNN models...",
            task=task,
            on_complete=on_complete,
        )

    def _suggest_archive_extract_root(self) -> Path:
        text = self.archive_extract_root_edit.text().strip()
        if text:
            return Path(text).expanduser()
        common = common_workspace_root_from_config(self.collect_config())
        if common is not None:
            return suggested_workspace_paths(common).get("archive_extract_root", common / "archive_extract")
        return suggested_workspace_paths(Path.cwd())["archive_extract_root"]


__all__ = ["WorkspaceControllerMixin"]
