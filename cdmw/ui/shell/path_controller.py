"""Path picker and workspace location helpers for the shell window."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtWidgets import QFileDialog, QGridLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QSizePolicy

from cdmw.services.archive_environment_service import autodetect_archive_package_roots
from cdmw.services.texture_workflow_service import common_workspace_root_from_config


class PathControllerMixin:
    """Shared browse buttons and path auto-detection for shell settings."""

    def _add_path_row(
        self,
        layout: QGridLayout,
        row: int,
        label_text: str,
        line_edit: QLineEdit,
        browse_handler: Callable[[], None],
    ) -> QPushButton:
        label = QLabel(label_text)
        label.setMinimumWidth(124)
        label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        browse_button = QPushButton("Browse")
        browse_button.setMinimumWidth(88)
        browse_button.clicked.connect(browse_handler)
        layout.addWidget(label, row, 0)
        layout.addWidget(line_edit, row, 1)
        layout.addWidget(browse_button, row, 2)
        return browse_button

    def _browse_directory(self, line_edit: QLineEdit, title: str) -> None:
        start_dir = self._pick_existing_directory(line_edit.text())
        selected = QFileDialog.getExistingDirectory(self, title, start_dir)
        if selected:
            line_edit.setText(selected)

    def _browse_file(self, line_edit: QLineEdit, title: str, file_filter: str, save_mode: bool = False) -> None:
        start_path = line_edit.text().strip() or str(Path.cwd())
        if save_mode:
            selected, _ = QFileDialog.getSaveFileName(self, title, start_path, file_filter)
        else:
            selected, _ = QFileDialog.getOpenFileName(self, title, start_path, file_filter)
        if selected:
            line_edit.setText(selected)

    def _pick_existing_directory(self, current_text: str) -> str:
        raw = current_text.strip()
        if not raw:
            return str(Path.cwd())
        path = Path(raw).expanduser()
        if path.is_file():
            return str(path.parent)
        if path.exists():
            return str(path)
        if path.parent.exists():
            return str(path.parent)
        return str(Path.cwd())

    def _browse_original_dds_root(self) -> None:
        self._browse_directory(self.original_dds_edit, "Select Original DDS Root")

    def _browse_png_root(self) -> None:
        self._browse_directory(self.png_root_edit, "Select PNG Root")

    def _browse_texture_editor_png_root(self) -> None:
        self._browse_directory(self.texture_editor_png_root_edit, "Select Texture Editor PNG Root")

    def _browse_dds_staging_root(self) -> None:
        self._browse_directory(self.dds_staging_root_edit, "Select DDS Staging PNG Root")

    def _browse_output_root(self) -> None:
        self._browse_directory(self.output_root_edit, "Select Output Root")

    def _browse_csv_log_path(self) -> None:
        self._browse_file(
            self.csv_log_path_edit,
            "Select CSV Log Path",
            "CSV files (*.csv);;All files (*.*)",
            save_mode=True,
        )

    def _browse_chainner_exe_path(self) -> None:
        self._browse_file(
            self.chainner_exe_path_edit,
            "Select chaiNNer executable",
            "Executable (*.exe);;All files (*.*)",
        )

    def _browse_chainner_chain_path(self) -> None:
        self._browse_file(
            self.chainner_chain_path_edit,
            "Select chaiNNer chain",
            "chaiNNer chain (*.chn);;All files (*.*)",
        )

    def _browse_ncnn_exe_path(self) -> None:
        self._browse_file(
            self.ncnn_exe_path_edit,
            "Select Real-ESRGAN NCNN executable",
            "Executable (*.exe);;All files (*.*)",
        )

    def _browse_ncnn_model_dir(self) -> None:
        self._browse_directory(self.ncnn_model_dir_edit, "Select Real-ESRGAN NCNN model folder")

    def _browse_mod_ready_export_root(self) -> None:
        self._browse_directory(self.mod_ready_export_root_edit, "Select Ready Mod Package Parent Root")

    def _browse_archive_package_root(self) -> None:
        self._browse_directory(self.archive_package_root_edit, "Select Archive Package Root")

    def _browse_archive_extract_root(self) -> None:
        self._browse_directory(self.archive_extract_root_edit, "Select Archive Extract Root")

    def autodetect_archive_package_root(
        self,
        _checked: bool = False,
        *,
        after_success: Optional[Callable[[], None]] = None,
    ) -> None:
        if self._background_task_active():
            return

        def task(on_log: Callable[[str], None]) -> List[str]:
            on_log("Auto-detecting Crimson Desert archive package roots from known install locations...")
            roots = autodetect_archive_package_roots(on_log=on_log)
            return [str(path) for path in roots]

        def on_complete(result: object) -> None:
            candidates = [str(item) for item in result] if isinstance(result, list) else []
            if not candidates:
                self.set_status_message(
                    "No valid Crimson Desert archive package root was auto-detected. Use Browse to set it manually.",
                    error=True,
                )
                return

            selected_path = candidates[0]
            if len(candidates) > 1:
                selected_path, accepted = QInputDialog.getItem(
                    self,
                    "Select Package Root",
                    "Multiple Crimson Desert package roots were found. Choose one:",
                    candidates,
                    0,
                    False,
                )
                if not accepted or not selected_path:
                    self.set_status_message("Archive package root auto-detect cancelled.")
                    return

            self.archive_package_root_edit.setText(selected_path)
            self.flush_settings_save()
            self._activate_tool_widget(self.archive_browser_tab)
            self.set_status_message(f"Auto-detected archive package root: {selected_path}")
            self.append_log(f"Using detected archive package root: {selected_path}")
            if after_success is not None:
                self._run_when_background_idle(after_success, label="continuing archive package setup")

        self._run_utility_task(
            status_message="Auto-detecting archive package root...",
            task=task,
            on_complete=on_complete,
        )

    def _suggest_workspace_base_dir(self) -> str:
        common = common_workspace_root_from_config(self.collect_config())
        if common is not None:
            return str(common)
        return str(Path.cwd())


__all__ = ["PathControllerMixin"]
