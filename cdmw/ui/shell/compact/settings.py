"""Settings-tab controls for selecting and theming Compact Workspace."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel

from cdmw.ui.shell.compact.config import (
    APPLICATION_LAYOUT_SELECTOR_EXPOSED,
    COMPACT_SHELL_THEME_SETTING,
    COMPACT_SHELL_VARIANT,
    DEFAULT_COMPACT_SHELL_THEME,
    LEGACY_SHELL_VARIANT,
    SHELL_VARIANT_SETTING,
    normalize_shell_variant,
    read_compact_shell_theme_key,
    read_shell_variant,
    theme_change_field,
)
from cdmw.ui.themes import UI_THEME_SCHEMES


class CompactWorkspaceSettingsMixin:
    def _build_compact_workspace_settings_ui(self) -> None:
        self._running_shell_variant = read_shell_variant(self.settings)
        self.application_layout_group = QGroupBox("Application layout")
        application_layout = QFormLayout(self.application_layout_group)
        application_layout.setContentsMargins(12, 14, 12, 12)
        application_layout.setHorizontalSpacing(12)
        application_layout.setVerticalSpacing(8)
        self.application_layout_combo = QComboBox()
        self.application_layout_combo.setObjectName("ApplicationLayoutCombo")
        self.application_layout_combo.addItem("Classic Workspace", LEGACY_SHELL_VARIANT)
        self.application_layout_combo.addItem("Compact Workspace", COMPACT_SHELL_VARIANT)
        application_layout.addRow("Application layout", self.application_layout_combo)
        self.compact_shell_theme_combo = QComboBox()
        self.compact_shell_theme_combo.setObjectName("CompactShellThemeCombo")
        for key, theme in UI_THEME_SCHEMES.items():
            self.compact_shell_theme_combo.addItem(theme["label"], key)
        self.compact_shell_theme_combo.setToolTip(
            "Compact Workspace has its own theme and never changes the Classic Workspace theme."
        )
        application_layout.addRow("Compact Workspace theme", self.compact_shell_theme_combo)
        self.application_layout_restart_label = QLabel()
        self.application_layout_restart_label.setObjectName("ApplicationLayoutRestartNotice")
        self.application_layout_restart_label.setWordWrap(True)
        application_layout.addRow("", self.application_layout_restart_label)
        self.application_layout_group.setVisible(APPLICATION_LAYOUT_SELECTOR_EXPOSED)
        self.layout_page_layout.addWidget(self.application_layout_group)

    def _connect_compact_workspace_settings(self) -> None:
        self.application_layout_combo.currentIndexChanged.connect(
            self._handle_application_layout_changed
        )
        self.compact_shell_theme_combo.currentIndexChanged.connect(
            self._handle_compact_shell_theme_changed
        )

    def _load_compact_workspace_settings(self) -> None:
        self.set_application_layout_selection(read_shell_variant(self.settings))
        self.set_compact_shell_theme_selection(read_compact_shell_theme_key(self.settings))
        self._update_application_layout_restart_notice()

    def _save_compact_workspace_settings(self) -> None:
        self.settings.setValue(SHELL_VARIANT_SETTING, self.current_application_layout())
        self.settings.setValue(COMPACT_SHELL_THEME_SETTING, self.current_compact_shell_theme())

    def _handle_application_layout_changed(self, *_args: object) -> None:
        self._update_application_layout_restart_notice()
        self.schedule_settings_save()

    def _handle_compact_shell_theme_changed(self, *_args: object) -> None:
        if not self._settings_ready:
            return
        theme_key = self.current_compact_shell_theme()
        self.settings.setValue(COMPACT_SHELL_THEME_SETTING, theme_key)
        self.schedule_settings_save()
        if self._running_shell_variant == COMPACT_SHELL_VARIANT:
            payload = {
                "theme_key": theme_key,
                "theme_target": COMPACT_SHELL_THEME_SETTING,
                "changed": (theme_change_field(COMPACT_SHELL_THEME_SETTING),),
                "requires_theme_apply": True,
                "requires_ui_fonts": True,
            }
            self.appearance_change_started.emit(dict(payload))
            self.appearance_changed.emit(payload)

    def set_application_layout_selection(self, shell_variant: object) -> None:
        index = self.application_layout_combo.findData(normalize_shell_variant(shell_variant))
        self.application_layout_combo.blockSignals(True)
        self.application_layout_combo.setCurrentIndex(max(0, index))
        self.application_layout_combo.blockSignals(False)

    def set_compact_shell_theme_selection(self, theme_key: object) -> None:
        resolved = str(theme_key or DEFAULT_COMPACT_SHELL_THEME)
        index = self.compact_shell_theme_combo.findData(resolved)
        if index < 0:
            index = self.compact_shell_theme_combo.findData(DEFAULT_COMPACT_SHELL_THEME)
        self.compact_shell_theme_combo.blockSignals(True)
        self.compact_shell_theme_combo.setCurrentIndex(max(0, index))
        self.compact_shell_theme_combo.blockSignals(False)

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

    def current_compact_shell_theme(self) -> str:
        data = self.compact_shell_theme_combo.currentData()
        candidate = str(data) if data is not None else DEFAULT_COMPACT_SHELL_THEME
        return candidate if candidate in UI_THEME_SCHEMES else DEFAULT_COMPACT_SHELL_THEME


__all__ = ["CompactWorkspaceSettingsMixin"]
