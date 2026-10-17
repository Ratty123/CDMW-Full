"""Settings controls for archive scan exclusions."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QListWidget, QMenu, QPushButton, QVBoxLayout,
)

from cdmw.domain.archives.discovery import (
    ARCHIVE_IGNORED_FOLDERS_SETTING, BUILTIN_IGNORED_ARCHIVE_FOLDERS,
    normalize_ignored_archive_folders,
)
from cdmw.services.settings_service import read_ignored_archive_folders


class ArchiveIgnoredFoldersGroup(QGroupBox):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setTitle("Ignored folders")
        self.settings = settings
        self.get_package_root = lambda: str(settings.value("archive/package_root", "") or "")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Always ignored at the game-folder root:"))
        self.builtin_folders_label = QLabel(", ".join(BUILTIN_IGNORED_ARCHIVE_FOLDERS))
        self.builtin_folders_label.setWordWrap(True)
        self.builtin_folders_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.builtin_folders_label)
        layout.addWidget(QLabel("Your ignored folders:"))
        self.folder_list = QListWidget()
        self.folder_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.folder_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.folder_list.customContextMenuRequested.connect(self._context_menu)
        self.folder_list.setMinimumHeight(100)
        self.folder_list.setMaximumHeight(220)
        self.folder_list.setToolTip(
            "Paths are relative to the selected game folder. A path such as extras/old excludes that folder and everything inside it."
        )
        layout.addWidget(self.folder_list)
        buttons = QHBoxLayout()
        self.add_folder_button = QPushButton("Add folder...")
        self.add_path_button = QPushButton("Add path...")
        self.remove_button = QPushButton("Remove selected")
        for button in (self.add_folder_button, self.add_path_button, self.remove_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.status_label = QLabel("Changes apply the next time archives are loaded or refreshed.")
        self.status_label.setWordWrap(True)
        self.status_label.setToolTip("Ignored files are unavailable to Archive Browser and tools using its catalogue. No files are deleted.")
        layout.addWidget(self.status_label)
        self.add_folder_button.clicked.connect(self._browse_folder)
        self.add_path_button.clicked.connect(self._enter_path)
        self.remove_button.clicked.connect(self.remove_selected)
        self.folder_list.itemSelectionChanged.connect(
            lambda: self.remove_button.setEnabled(bool(self.folder_list.selectedItems()))
        )
        self.reload()

    def reload(self):
        self.folder_list.clear()
        self.folder_list.addItems(read_ignored_archive_folders(self.settings))
        self.remove_button.setEnabled(False)

    def add_path(self, path: str) -> bool:
        try:
            folders = normalize_ignored_archive_folders(
                [*(self.folder_list.item(row).text() for row in range(self.folder_list.count())), path]
            )
        except ValueError:
            self.status_label.setText("Enter a folder path relative to the game folder, without wildcards or '..'.")
            return False
        builtins = {name.casefold() for name in BUILTIN_IGNORED_ARCHIVE_FOLDERS}
        folders = tuple(folder for folder in folders if folder.casefold().split("/")[0] not in builtins)
        self.folder_list.clear()
        self.folder_list.addItems(folders)
        self._save()
        return True

    def remove_selected(self):
        for item in self.folder_list.selectedItems():
            self.folder_list.takeItem(self.folder_list.row(item))
        self._save()

    def _save(self):
        folders = [self.folder_list.item(row).text() for row in range(self.folder_list.count())]
        self.settings.setValue(ARCHIVE_IGNORED_FOLDERS_SETTING, folders)
        self.settings.sync()
        self.status_label.setText("Changes apply the next time archives are loaded or refreshed.")

    def _enter_path(self):
        path, accepted = QInputDialog.getText(self, "Ignore folder", "Folder path relative to the game folder:")
        if accepted and path.strip():
            self.add_path(path)

    def _browse_folder(self):
        root_text = self.get_package_root().strip()
        if not root_text:
            self.status_label.setText("Set the game folder in Archive Locations first.")
            return
        selected = QFileDialog.getExistingDirectory(self, "Select folder to ignore", root_text)
        if not selected:
            return
        try:
            relative = Path(selected).absolute().relative_to(Path(root_text).absolute())
        except ValueError:
            self.status_label.setText("Choose a folder inside the selected game folder.")
            return
        self.add_path(relative.as_posix())

    def _context_menu(self, position):
        item = self.folder_list.itemAt(position)
        if item is not None and not item.isSelected():
            self.folder_list.clearSelection()
            item.setSelected(True)
        if not self.folder_list.selectedItems():
            return
        menu = QMenu(self)
        menu.addAction("Remove selected", self.remove_selected)
        menu.exec(self.folder_list.viewport().mapToGlobal(position))
