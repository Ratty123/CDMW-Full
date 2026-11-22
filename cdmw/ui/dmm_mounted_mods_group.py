"""Settings > Paths: show the mods DMM serves at run time in place of the game's files (experimental)."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, QTimer
from PySide6.QtWidgets import QCheckBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from cdmw.services.dmm_runtime_mount import (
    SHOW_MOUNTED_MODS_SETTING, current_overlay, describe_mount, setting_enabled,
)

DMM_MOUNTED_MODS_TOOLTIP = (
    "DMM 5 leaves the game's archive folders vanilla and serves its mods to the game while it runs. "
    "With this on, CDMW reads DMM's list (bin64\\dmm\\manifest.tsv) and opens and previews the file DMM "
    "serves in place of the game's own, so a mesh you mounted in DMM opens as the game shows it. "
    "Game tables stay the game's own. CDMW never changes anything of DMM's. Experimental."
)


class DmmMountedModsGroup(QGroupBox):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setTitle("Mods mounted in DMM (experimental)")
        self.settings = settings
        self.get_package_root = lambda: str(settings.value("archive/package_root", "") or "")
        layout = QVBoxLayout(self)
        self.show_checkbox = QCheckBox("Show the files DMM serves the game in place of the game's own")
        self.show_checkbox.setObjectName("DmmShowMountedMods")
        self.show_checkbox.setToolTip(DMM_MOUNTED_MODS_TOOLTIP)
        self.show_checkbox.setChecked(current_overlay().enabled)
        layout.addWidget(self.show_checkbox)
        row = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setObjectName("DmmMountedModsStatus")
        self.status_label.setWordWrap(True)
        row.addWidget(self.status_label, 1)
        self.refresh_button = QPushButton("Check again")
        self.refresh_button.setToolTip("Read DMM's list again, for example after Mount or Unmount in DMM.")
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        hint = QLabel("Files you already opened keep what they showed. Open them again after you mount in DMM.")
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.show_checkbox.toggled.connect(self._toggled)
        self.refresh_button.clicked.connect(self.check_again)
        # Typing a game folder reads DMM's list once the typing pauses, not once per key.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(300)
        self._refresh_timer.timeout.connect(self.refresh)
        self.refresh()

    def bind_game_folder(self, field) -> None:
        """Follow the game-folder field as it is edited, not only the folder last saved."""

        self.get_package_root = field.text
        field.textChanged.connect(self._refresh_soon)
        self.refresh()

    def _refresh_soon(self, *_args) -> None:
        self._refresh_timer.start()

    def reload(self) -> None:
        """Show the saved choice again (a profile import, for example); the overlay follows it."""

        enabled = setting_enabled(self.settings)
        current_overlay().set_enabled(enabled)
        with QSignalBlocker(self.show_checkbox):
            self.show_checkbox.setChecked(enabled)
        self.refresh()

    def _toggled(self, checked: bool) -> None:
        current_overlay().set_enabled(checked)
        self.settings.setValue(SHOW_MOUNTED_MODS_SETTING, bool(checked))
        self.refresh()

    def check_again(self) -> None:
        """Read DMM's list and the game's build again; Browse drops what it kept from before."""
        current_overlay().refresh(self.get_package_root())
        self.refresh()

    def refresh(self) -> None:
        state = describe_mount(self.get_package_root())
        self.status_label.setText(str(state["message"]))
        self.status_label.setToolTip("\n".join(f"{row['mod']}: {row['files']:,} file(s)" for row in state["mods"]))
