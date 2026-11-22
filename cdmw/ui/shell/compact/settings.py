"""Settings-tab controls for selecting the application layout."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel

from cdmw.ui.shell.compact.config import (
    APPLICATION_LAYOUT_SELECTOR_EXPOSED,
    COMPACT_SHELL_VARIANT,
    LEGACY_SHELL_VARIANT,
    SHELL_VARIANT_SETTING,
    normalize_shell_variant,
    read_shell_variant,
)


class CompactWorkspaceSettingsMixin:
    def _build_compact_workspace_settings_ui(self, appearance_layout: QFormLayout) -> None:
        self._running_shell_variant = read_shell_variant(self.settings)
        host = appearance_layout.parentWidget()
        self.application_layout_combo = QComboBox(host)
        self.application_layout_combo.setObjectName("ApplicationLayoutCombo")
        self.application_layout_combo.addItem("Compact Workspace", COMPACT_SHELL_VARIANT)
        self.application_layout_restart_label = QLabel(host)
        self.application_layout_restart_label.setObjectName("ApplicationLayoutRestartNotice")
        self.application_layout_restart_label.setWordWrap(True)
        if APPLICATION_LAYOUT_SELECTOR_EXPOSED:
            appearance_layout.addRow("Layout", self.application_layout_combo)
        else:
            self.application_layout_combo.setVisible(False)
        # The notice is not in a layout yet; showing it now would open it as a window of
        # its own for a moment. _show_compact_workspace_settings_notice shows it once placed.
        self.application_layout_restart_label.setVisible(False)

    def _show_compact_workspace_settings_notice(self, appearance_layout: QFormLayout | None = None) -> None:
        if APPLICATION_LAYOUT_SELECTOR_EXPOSED:
            if appearance_layout is not None:
                appearance_layout.addRow("", self.application_layout_restart_label)
            self.application_layout_restart_label.setVisible(True)
        else:
            self.application_layout_restart_label.setVisible(False)

    def _connect_compact_workspace_settings(self) -> None:
        self.application_layout_combo.currentIndexChanged.connect(
            self._handle_application_layout_changed
        )

    def _load_compact_workspace_settings(self) -> None:
        self.set_application_layout_selection(read_shell_variant(self.settings))
        self._update_application_layout_restart_notice()

    def _save_compact_workspace_settings(self) -> None:
        self.settings.setValue(SHELL_VARIANT_SETTING, self.current_application_layout())

    def _handle_application_layout_changed(self, *_args: object) -> None:
        self._update_application_layout_restart_notice()
        self.schedule_settings_save()

    def set_application_layout_selection(self, shell_variant: object) -> None:
        index = self.application_layout_combo.findData(normalize_shell_variant(shell_variant))
        self.application_layout_combo.blockSignals(True)
        self.application_layout_combo.setCurrentIndex(max(0, index))
        self.application_layout_combo.blockSignals(False)

    def _update_application_layout_restart_notice(self) -> None:
        selected = self.current_application_layout()
        if selected != self._running_shell_variant:
            self.application_layout_restart_label.setText(
                "Restart required: the saved application layout will be used the next time the app starts."
            )
        else:
            self.application_layout_restart_label.setText(
                "Application layout changes take effect after restarting the app."
            )

    def current_application_layout(self) -> str:
        return normalize_shell_variant(self.application_layout_combo.currentData())

__all__ = ["CompactWorkspaceSettingsMixin"]
