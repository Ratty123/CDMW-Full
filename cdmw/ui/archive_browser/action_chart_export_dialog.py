"""Name an edited action chart's DMM mod and choose where it goes."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

SEND_TO_DMM = "dmm"
SAVE_FOLDER = "folder"


class ActionChartExportDialog(QDialog):
    """Mod details plus the choice: straight into DMM's mods folder, or a folder of your own."""

    def __init__(
        self,
        *,
        title: str,
        description: str,
        author: str = "",
        version: str = "1.0",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.choice = ""
        self.setWindowTitle("Export Action Chart Mod")
        self.resize(620, 360)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "The edited chart is written as a DMM mod: an archive folder with manifest.json and modinfo.json. "
            "Send to DMM puts it in DMM's mods folder; enable it in DMM and click Mount. "
            "A mod CDMW wrote earlier under the same name is replaced."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.title_edit = QLineEdit(title)
        self.author_edit = QLineEdit(author)
        self.version_edit = QLineEdit(version or "1.0")
        self.description_edit = QPlainTextEdit(description)
        form.addRow(QLabel("Mod name:"), self.title_edit)
        form.addRow(QLabel("Author:"), self.author_edit)
        form.addRow(QLabel("Version:"), self.version_edit)
        form.addRow(QLabel("Description:"), self.description_edit)
        layout.addLayout(form, 1)
        self.keep_checkbox = QCheckBox("Keep the other charts already in a mod with this name")
        self.keep_checkbox.setToolTip(
            "Export several charts under one mod name to ship a whole moveset as one DMM mod. "
            "This chart replaces its own earlier version."
        )
        self.keep_checkbox.setChecked(True)
        layout.addWidget(self.keep_checkbox)
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #d9534f;")
        layout.addWidget(self.error_label)
        buttons = QHBoxLayout()
        self.send_button = QPushButton("Send to DMM")
        self.send_button.setDefault(True)
        self.send_button.clicked.connect(lambda: self._choose(SEND_TO_DMM))
        self.folder_button = QPushButton("Save Mod Folder...")
        self.folder_button.clicked.connect(lambda: self._choose(SAVE_FOLDER))
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(self.send_button)
        buttons.addWidget(self.folder_button)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    @property
    def mod_title(self) -> str:
        return self.title_edit.text().strip()

    @property
    def mod_author(self) -> str:
        return self.author_edit.text().strip()

    @property
    def mod_version(self) -> str:
        return self.version_edit.text().strip() or "1.0"

    @property
    def keep_existing(self) -> bool:
        return self.keep_checkbox.isChecked()

    @property
    def mod_description(self) -> str:
        return self.description_edit.toPlainText().strip()

    def _choose(self, choice: str) -> None:
        if not self.mod_title:
            self.error_label.setText("Name the mod first.")
            return
        self.choice = choice
        self.accept()


__all__ = ["ActionChartExportDialog", "SAVE_FOLDER", "SEND_TO_DMM"]
