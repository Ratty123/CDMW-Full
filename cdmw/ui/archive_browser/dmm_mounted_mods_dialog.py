"""Compatibility QDialog wrapper around Mod Management > Mounted in DMM."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from cdmw.ui.tools.dmm_mounted_mods_page import (
    DmmMountedFileRow,
    DmmMountedModsPage,
    _prepare_open_row,
    _prepare_texture_row,
)


class DmmMountedModsDialog(QDialog):
    """Standalone dialog view wrapping :class:`DmmMountedModsPage` for legacy callers."""

    def __init__(self, archive, parent: QWidget | None = None) -> None:
        parent_widget = parent if parent is not None else (archive if isinstance(archive, QWidget) else None)
        super().__init__(parent_widget)
        self.setObjectName("DmmMountedModsDialog")
        self.setWindowTitle(self.tr("DMM Mounted Mods"))
        self.resize(1040, 660)
        self.setMinimumSize(780, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.page = DmmMountedModsPage(
            archive,
            self,
            on_navigated=self.accept,
            show_close_button=True,
        )
        layout.addWidget(self.page, 1)

        self.enabled_checkbox = self.page.enabled_checkbox
        self.refresh_button = self.page.refresh_button
        self.copy_report_button = self.page.copy_report_button
        self.notice_label = self.page.notice_label
        self.status_label = self.page.status_label
        self.search_edit = self.page.search_edit
        self.mod_tree = self.page.mod_tree
        self.kind_combo = self.page.kind_combo
        self.file_tree = self.page.file_tree
        self.detail_label = self.page.detail_label
        self.filter_browse_button = self.page.filter_browse_button
        self.show_in_browse_button = self.page.show_in_browse_button
        self.open_mesh_button = self.page.open_mesh_button
        self.open_texture_button = self.page.open_texture_button
        self.copy_button = self.page.copy_button
        self.show_source_button = self.page.show_source_button
        self.close_button = self.page.close_button
        self.open_mod_folder_button = self.page.open_mod_folder_button

        if self.close_button is not None:
            self.close_button.clicked.connect(self.close)

    @property
    def _all_rows(self):
        return self.page._all_rows

    @property
    def _rows_by_path(self):
        return self.page._rows_by_path

    def reload(self) -> None:
        self.page.reload()

    def refresh_from_dmm(self) -> None:
        self.page.refresh_from_dmm()

    def visible_rows(self) -> list[DmmMountedFileRow]:
        return self.page.visible_rows()

    def selected_rows(self) -> list[DmmMountedFileRow]:
        return self.page.selected_rows()

    def select_paths(self, paths) -> list[str]:
        return self.page.select_paths(paths)

    def selected_mod(self) -> str:
        return self.page.selected_mod()

    def select_mod(self, mod: str) -> bool:
        return self.page.select_mod(mod)

    def filter_browse_archives(self) -> bool:
        return self.page.filter_browse_archives()

    def show_selected_in_browse(self) -> bool:
        return self.page.show_selected_in_browse()

    def open_selected_in_mesh_editor(self) -> str:
        return self.page.open_selected_in_mesh_editor()

    def open_selected_in_texture_editor(self) -> str:
        return self.page.open_selected_in_texture_editor()

    def copy_selected(self, folder: Path | str) -> list[str]:
        return self.page.copy_selected(folder)

    def copy_selected_dialog(self) -> None:
        self.page.copy_selected_dialog()

    def show_selected_source(self) -> None:
        self.page.show_selected_source()

    def copy_overlap_report(self) -> str:
        return self.page.copy_overlap_report()

    def open_selected_mod_folder(self) -> bool:
        return self.page.open_selected_mod_folder()

    def reject(self) -> None:
        self.page.request_shutdown()
        super().reject()

    def accept(self) -> None:
        self.page.request_shutdown()
        super().accept()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.page.request_shutdown()
        super().closeEvent(event)


def show_dmm_mounted_mods_dialog(archive) -> DmmMountedModsDialog:
    """Open or focus the standalone DMM Mounted Mods dialog."""

    from shiboken6 import isValid

    existing = getattr(archive, "_dmm_mounted_mods_dialog", None)
    if existing is not None and isValid(existing) and existing.isVisible():
        existing.reload()
        existing.raise_()
        existing.activateWindow()
        return existing
    dialog = DmmMountedModsDialog(archive)
    archive._dmm_mounted_mods_dialog = dialog
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog


__all__ = [
    "DmmMountedFileRow",
    "DmmMountedModsDialog",
    "_prepare_open_row",
    "_prepare_texture_row",
    "show_dmm_mounted_mods_dialog",
]
