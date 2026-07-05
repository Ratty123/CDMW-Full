from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QPushButton, QVBoxLayout, QWidget

from cdmw.ui.settings_tab import SettingsTab
from cdmw.ui.shell.theme_controller import ThemeChangeBusyOverlay, ThemeControllerMixin, apply_app_fonts
from cdmw.ui.themes import build_app_stylesheet


class _Settings:
    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def value(self, key: str, default: object = None) -> object:
        return self._values.get(key, default)


class ShellThemeControllerTests(unittest.TestCase):
    def test_application_ui_font_change_refreshes_archive_controls_font(self) -> None:
        app = QApplication.instance() or QApplication([])
        previous_font = QFont(app.font())

        class _Window(QWidget, ThemeControllerMixin):
            def __init__(self) -> None:
                super().__init__()
                self.settings = _Settings(
                    {
                        "appearance/ui_font_family": previous_font.family(),
                        "appearance/ui_font_size": 14,
                        "appearance/data_font_size": 11,
                        "appearance/ui_density": "compact",
                    }
                )
                self.archive_controls_group = QWidget(self)

        window = _Window()
        try:
            stale_font = QFont(previous_font)
            stale_font.setPointSize(9)
            window.archive_controls_group.setFont(stale_font)

            ui_font = QFont(previous_font)
            ui_font.setPointSize(14)
            window._sync_archive_controls_font(ui_font)

            self.assertEqual(13, window.archive_controls_group.font().pointSize())
        finally:
            window.deleteLater()
            app.setFont(previous_font)

    def test_theme_change_busy_overlay_updates_state_and_timers(self) -> None:
        app = QApplication.instance() or QApplication([])
        parent = QWidget()
        parent.resize(320, 180)
        parent.show()
        overlay = ThemeChangeBusyOverlay(parent)

        overlay.show_appearance_change("graphite", title="Applying Graphite", detail="Working")
        app.processEvents()

        self.assertEqual("ThemeChangeBusyOverlay", overlay.objectName())
        self.assertTrue(overlay.isVisible())
        self.assertEqual(parent.rect(), overlay.geometry())

        overlay.finish(0)
        app.processEvents()
        overlay.deleteLater()
        parent.deleteLater()

    def test_apply_app_fonts_updates_existing_styled_child_controls(self) -> None:
        app = QApplication.instance() or QApplication([])
        previous_font = QFont(app.font())
        previous_style_sheet = app.styleSheet()
        parent = QWidget()
        label = QLabel("Label")
        button = QPushButton("Button")
        list_widget = QListWidget()
        layout = QVBoxLayout(parent)
        layout.addWidget(label)
        layout.addWidget(button)
        layout.addWidget(list_widget)
        try:
            app.setStyleSheet(build_app_stylesheet("graphite"))
            parent.show()
            app.processEvents()

            settings = _Settings(
                {
                    "appearance/ui_font_family": previous_font.family(),
                    "appearance/ui_font_size": 15,
                    "appearance/data_font_size": 11,
                    "appearance/ui_density": "comfortable",
                }
            )
            apply_app_fonts(app, settings, screen_width=4096, screen_height=2160)
            app.processEvents()

            self.assertEqual(15, label.font().pointSize())
            self.assertEqual(15, button.font().pointSize())
            self.assertEqual(11, list_widget.font().pointSize())
        finally:
            parent.deleteLater()
            app.setFont(previous_font)
            for class_name in (
                "QWidget",
                "QListView",
                "QListWidget",
                "QTreeView",
                "QTreeWidget",
                "QTableView",
                "QTableWidget",
                "QHeaderView",
            ):
                app.setFont(previous_font, class_name)
            app.setStyleSheet(previous_style_sheet)

    def test_settings_appearance_payload_routes_font_changes_without_full_theme_apply(self) -> None:
        previous = {
            "theme": "graphite",
            "ui_font_family": "Segoe UI",
            "ui_density": "compact",
            "ui_font_size": 10,
            "data_font_size": 9,
            "log_font_family": "Consolas",
            "log_font_size": 10,
            "log_font_bold": True,
            "log_text_style": "rich",
            "log_color_scheme": "theme",
            "preview_color_scheme": "theme",
        }
        current = dict(previous)
        current["ui_font_size"] = 12

        payload = SettingsTab._appearance_change_payload(object(), previous, current)  # type: ignore[arg-type]

        self.assertEqual(("ui_font_size",), payload["changed"])
        self.assertFalse(payload["requires_theme_apply"])
        self.assertTrue(payload["requires_ui_fonts"])
        self.assertFalse(payload["requires_data_fonts"])
        self.assertFalse(payload["requires_text_colors"])

    def test_settings_appearance_payload_keeps_theme_and_text_routes_separate(self) -> None:
        previous = {
            "theme": "graphite",
            "ui_font_family": "Segoe UI",
            "ui_density": "compact",
            "ui_font_size": 10,
            "data_font_size": 9,
            "log_font_family": "Consolas",
            "log_font_size": 10,
            "log_font_bold": True,
            "log_text_style": "rich",
            "log_color_scheme": "theme",
            "preview_color_scheme": "theme",
        }

        theme_current = dict(previous)
        theme_current["theme"] = "light"
        theme_payload = SettingsTab._appearance_change_payload(object(), previous, theme_current)  # type: ignore[arg-type]
        self.assertTrue(theme_payload["requires_theme_apply"])
        self.assertFalse(theme_payload["requires_ui_fonts"])

        log_current = dict(previous)
        log_current["log_font_size"] = 12
        log_payload = SettingsTab._appearance_change_payload(object(), previous, log_current)  # type: ignore[arg-type]
        self.assertFalse(log_payload["requires_theme_apply"])
        self.assertFalse(log_payload["requires_ui_fonts"])
        self.assertTrue(log_payload["requires_data_fonts"])

        color_current = dict(previous)
        color_current["log_color_scheme"] = "terminal"
        color_payload = SettingsTab._appearance_change_payload(object(), previous, color_current)  # type: ignore[arg-type]
        self.assertFalse(color_payload["requires_theme_apply"])
        self.assertFalse(color_payload["requires_ui_fonts"])
        self.assertFalse(color_payload["requires_data_fonts"])
        self.assertTrue(color_payload["requires_text_colors"])


if __name__ == "__main__":
    unittest.main()
