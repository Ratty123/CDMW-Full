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
        self.setProperty(
            "compactPresentation",
            self._running_shell_variant == COMPACT_SHELL_VARIANT,
        )
        self.application_layout_combo = QComboBox()
        self.application_layout_combo.setObjectName("ApplicationLayoutCombo")
        self.application_layout_combo.addItem("Classic Workspace", LEGACY_SHELL_VARIANT)
        self.application_layout_combo.addItem("Compact Workspace", COMPACT_SHELL_VARIANT)
        appearance_layout.addRow("Layout", self.application_layout_combo)
        self.application_layout_restart_label = QLabel()
        self.application_layout_restart_label.setObjectName("ApplicationLayoutRestartNotice")
        self.application_layout_restart_label.setWordWrap(True)
        layout_label = appearance_layout.labelForField(self.application_layout_combo)
        if layout_label is not None:
            layout_label.setVisible(APPLICATION_LAYOUT_SELECTOR_EXPOSED)
        self.application_layout_combo.setVisible(APPLICATION_LAYOUT_SELECTOR_EXPOSED)
        self.application_layout_restart_label.setVisible(APPLICATION_LAYOUT_SELECTOR_EXPOSED)

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
